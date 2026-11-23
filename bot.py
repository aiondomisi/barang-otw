import logging
import os
import sqlite3
from datetime import datetime

import aiosqlite
import discord
import httpx
from discord import app_commands
from discord.ext import tasks

TOKEN = os.environ["DISCORD_TOKEN"]
SHIP24_KEY = os.environ["SHIP24_API_KEY"]
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "30"))
DB_PATH = os.getenv("DB_PATH", "/data/tracker.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pos-tracker")

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_number TEXT NOT NULL,
    label TEXT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    tracker_id TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tracking_number, user_id)
);
CREATE TABLE IF NOT EXISTS seen (
    parcel_id INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    PRIMARY KEY (parcel_id, event_id)
);
"""


class Ship24:
    def __init__(self, key: str):
        self.http = httpx.AsyncClient(
            base_url="https://api.ship24.com/public/v1",
            headers={"Authorization": f"Bearer {key}"},
            timeout=90,  # first call can take up to a minute
        )

    @staticmethod
    def _first(resp: httpx.Response) -> dict | None:
        resp.raise_for_status()
        trackings = resp.json().get("data", {}).get("trackings", [])
        return trackings[0] if trackings else None

    async def create(self, number: str, courier: str | None = None) -> dict | None:
        body = {"trackingNumber": number}
        if courier:
            body["courierCode"] = [courier]
        return self._first(await self.http.post("/trackers/track", json=body))

    async def couriers(self) -> list[dict]:
        resp = await self.http.get("/couriers")
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("couriers", [])
        # Malaysian couriers first, then alphabetical
        return sorted(
            (c for c in items if not c.get("isDeprecated")),
            key=lambda c: (c.get("countryCode") != "MY", c["courierName"].lower()),
        )

    async def results(self, tracker_id: str) -> dict | None:
        return self._first(await self.http.get(f"/trackers/{tracker_id}/results"))


def sorted_events(tracking: dict) -> list[dict]:
    events = tracking.get("events") or []
    return sorted(events, key=lambda e: e.get("occurrenceDatetime") or "")


def event_key(ev: dict) -> str:
    return str(
        ev.get("eventId") or f"{ev.get('occurrenceDatetime')}|{ev.get('status')}"
    )


def is_delivered(tracking: dict) -> bool:
    return (tracking.get("shipment") or {}).get("statusMilestone") == "delivered"


def build_embed(
    number: str, label: str | None, tracking: dict, events: list[dict]
) -> discord.Embed:
    milestone = (tracking.get("shipment") or {}).get("statusMilestone", "unknown")
    embed = discord.Embed(
        title=f"📦 {label or number}",
        description=f"`{number}` · **{milestone.replace('_', ' ').title()}**",
        color=(
            discord.Color.green()
            if milestone == "delivered"
            else discord.Color.blurple()
        ),
    )
    for ev in events[-5:]:
        when = ev.get("occurrenceDatetime")
        try:
            name = f"<t:{int(datetime.fromisoformat(when).timestamp())}:f>"
        except (TypeError, ValueError):
            name = "Unknown time"
        text = ev.get("status") or "Update"
        if ev.get("location"):
            text += f"\n📍 {ev['location']}"
        embed.add_field(name=name, value=text, inline=False)
    return embed


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.ship24 = Ship24(SHIP24_KEY)
        self.db: aiosqlite.Connection
        self.couriers: list[dict] = []

    async def setup_hook(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.db = await aiosqlite.connect(DB_PATH)
        await self.db.executescript(SCHEMA)
        await self.db.commit()
        try:
            self.couriers = await self.ship24.couriers()
            log.info("Loaded %d couriers", len(self.couriers))
        except httpx.HTTPError:
            log.exception("Could not load courier list; courier autocomplete disabled")
        await self.tree.sync()
        self.poll.start()

    async def notify(self, parcel: tuple, embed: discord.Embed):
        _, _, _, user_id, channel_id, *_ = parcel
        content = f"<@{user_id}>"
        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(
                channel_id
            )
            await channel.send(content, embed=embed)
        except discord.DiscordException:
            user = await self.fetch_user(user_id)
            await user.send(embed=embed)

    @tasks.loop(minutes=POLL_MINUTES)
    async def poll(self):
        async with self.db.execute(
            "SELECT id, tracking_number, label, user_id, channel_id, tracker_id FROM parcels WHERE done = 0"
        ) as cur:
            parcels = await cur.fetchall()

        for parcel in parcels:
            pid, number, label, *_, tracker_id = parcel
            try:
                tracking = await self.ship24.results(tracker_id)
                if not tracking:
                    continue

                async with self.db.execute(
                    "SELECT event_id FROM seen WHERE parcel_id = ?", (pid,)
                ) as cur:
                    seen = {row[0] for row in await cur.fetchall()}
                new = [e for e in sorted_events(tracking) if event_key(e) not in seen]

                if new:
                    await self.notify(parcel, build_embed(number, label, tracking, new))
                    await self.db.executemany(
                        "INSERT OR IGNORE INTO seen VALUES (?, ?)",
                        [(pid, event_key(e)) for e in new],
                    )

                tracker = tracking.get("tracker") or {}
                if is_delivered(tracking) or tracker.get("isTracked") is False:
                    await self.db.execute(
                        "UPDATE parcels SET done = 1 WHERE id = ?", (pid,)
                    )
                await self.db.commit()
            except Exception:
                log.exception("Failed polling %s", number)

    @poll.before_loop
    async def before_poll(self):
        await self.wait_until_ready()


bot = Bot()
track = app_commands.Group(name="track", description="Pos Malaysia parcel tracking")


def channel_error(
    interaction: discord.Interaction, channel: discord.TextChannel | None
) -> str | None:
    if channel is None:
        return None
    mine = channel.permissions_for(channel.guild.me)
    if not (mine.view_channel and mine.send_messages and mine.embed_links):
        return f"I can't post embeds in {channel.mention}."
    if not channel.permissions_for(interaction.user).send_messages:
        return f"You can't send messages in {channel.mention}."
    return None


@track.command(name="add", description="Start tracking a parcel")
@app_commands.describe(
    number="Tracking number",
    courier="Courier (leave empty to auto-detect)",
    label="Optional name, e.g. 'Shopee order'",
    channel="Where to post updates (default: this channel)",
)
async def add(
    interaction: discord.Interaction,
    number: str,
    courier: str | None = None,
    label: str | None = None,
    channel: discord.TextChannel | None = None,
):
    number = number.strip().upper()
    if (
        courier
        and bot.couriers
        and courier not in {c["courierCode"] for c in bot.couriers}
    ):
        return await interaction.response.send_message(
            "Pick a courier from the dropdown list.", ephemeral=True
        )
    if error := channel_error(interaction, channel):
        return await interaction.response.send_message(error, ephemeral=True)
    channel_id = channel.id if channel else interaction.channel_id
    await interaction.response.defer()
    try:
        tracking = await bot.ship24.create(number, courier)
    except httpx.HTTPStatusError as e:
        return await interaction.followup.send(
            f"Ship24 error {e.response.status_code}: `{e.response.text[:300]}`"
        )
    except httpx.HTTPError as e:
        return await interaction.followup.send(f"Ship24 error: `{e}`")
    if not tracking:
        return await interaction.followup.send(
            "Ship24 returned no data for that number."
        )

    tracker_id = tracking["tracker"]["trackerId"]
    try:
        cur = await bot.db.execute(
            "INSERT INTO parcels (tracking_number, label, user_id, channel_id, tracker_id) VALUES (?, ?, ?, ?, ?)",
            (number, label, interaction.user.id, channel_id, tracker_id),
        )
    except sqlite3.IntegrityError:
        return await interaction.followup.send("You're already tracking that number.")

    events = sorted_events(tracking)
    await bot.db.executemany(
        "INSERT OR IGNORE INTO seen VALUES (?, ?)",
        [(cur.lastrowid, event_key(e)) for e in events],
    )
    if is_delivered(tracking):
        await bot.db.execute(
            "UPDATE parcels SET done = 1 WHERE id = ?", (cur.lastrowid,)
        )
    await bot.db.commit()

    embed = build_embed(number, label, tracking, events)
    if not events:
        embed.set_footer(
            text="No events yet. You'll be notified when the first one appears."
        )
    await interaction.followup.send(embed=embed)


@add.autocomplete("courier")
async def courier_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    q = current.lower().strip()
    matches = [
        c
        for c in bot.couriers
        if q in c["courierName"].lower() or q in c["courierCode"].lower()
    ]
    return [
        app_commands.Choice(
            name=f"{c['courierName']} ({c.get('countryCode') or '??'})"[:100],
            value=c["courierCode"],
        )
        for c in matches[:25]
    ]


@track.command(name="list", description="List your active parcels")
async def list_parcels(interaction: discord.Interaction):
    async with bot.db.execute(
        "SELECT tracking_number, label FROM parcels WHERE user_id = ? AND done = 0",
        (interaction.user.id,),
    ) as cur:
        rows = await cur.fetchall()
    text = (
        "\n".join(f"• `{n}`" + (f" — {l}" if l else "") for n, l in rows)
        or "Nothing being tracked."
    )
    await interaction.response.send_message(text, ephemeral=True)


@track.command(name="remove", description="Stop tracking a parcel")
async def remove(interaction: discord.Interaction, number: str):
    number = number.strip().upper()
    cur = await bot.db.execute(
        "DELETE FROM parcels WHERE tracking_number = ? AND user_id = ?",
        (number, interaction.user.id),
    )
    await bot.db.commit()
    await interaction.response.send_message(
        "Removed." if cur.rowcount else "Not found.", ephemeral=True
    )


@track.command(name="status", description="Show the latest status now")
async def status(interaction: discord.Interaction, number: str):
    number = number.strip().upper()
    async with bot.db.execute(
        "SELECT label, tracker_id FROM parcels WHERE tracking_number = ? AND user_id = ?",
        (number, interaction.user.id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message(
            "Not tracking that number.", ephemeral=True
        )
    await interaction.response.defer()
    tracking = await bot.ship24.results(row[1])
    if not tracking:
        return await interaction.followup.send("No data yet.")
    await interaction.followup.send(
        embed=build_embed(number, row[0], tracking, sorted_events(tracking))
    )


@track.command(name="channel", description="Change where a parcel's updates are posted")
@app_commands.describe(number="Tracking number", channel="New channel for updates")
async def set_channel(
    interaction: discord.Interaction, number: str, channel: discord.TextChannel
):
    number = number.strip().upper()
    if error := channel_error(interaction, channel):
        return await interaction.response.send_message(error, ephemeral=True)
    cur = await bot.db.execute(
        "UPDATE parcels SET channel_id = ? WHERE tracking_number = ? AND user_id = ?",
        (channel.id, number, interaction.user.id),
    )
    await bot.db.commit()
    msg = (
        f"Updates for `{number}` now go to {channel.mention}."
        if cur.rowcount
        else "Not found."
    )
    await interaction.response.send_message(msg, ephemeral=True)


bot.tree.add_command(track)

if __name__ == "__main__":
    bot.run(TOKEN)
