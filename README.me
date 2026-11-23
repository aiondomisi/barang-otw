# 📦 Barang OTW

A small, self-hosted Discord bot that watches your parcels and pings you when something changes. Built for Pos Malaysia, but it works with most couriers.

You give it a tracking number once. It checks in the background and only speaks up when there's actually news. No more refreshing a tracking page six times a day.

## What it does

- Tracks parcels from Pos Malaysia, J&T, Ninja Van, GDex, DHL and more (via [Ship24](https://www.ship24.com))
- Posts a message in the channel of your choice when a new tracking event shows up
- Stops tracking by itself once the parcel is delivered
- Keeps everything else (who tracks what, where to post) in a local SQLite file on your own machine

## Before you start

You'll need:

1. **A Discord bot token.** Create an application at the [Discord Developer Portal](https://discord.com/developers/applications), add a bot, and copy its token. No privileged intents are needed.
2. **A Ship24 API key.** Sign up at [ship24.com](https://www.ship24.com) and grab a key from the dashboard. The free tier covers 10 shipments a month, which is plenty for personal use.
3. **Docker** and Docker Compose.

## Setup

```bash
cp .env.example .env
# open .env and fill in DISCORD_TOKEN and SHIP24_API_KEY

docker compose up -d --build
```

Then invite the bot to your server using an OAuth2 URL with the `bot` and `applications.commands` scopes. In the channels where it should post, give it permission to view the channel, send messages and embed links.

Your data lives in `./data`, so rebuilding or updating the container won't wipe your tracked parcels.

## Using it

| Command | What it does |
| --- | --- |
| `/track add <number>` | Start tracking a parcel and show where it is right now |
| `/track list` | Show your active parcels (only you can see this) |
| `/track status <number>` | Check the latest status on demand |
| `/track channel <number> <channel>` | Change where updates for a parcel are posted |
| `/track remove <number>` | Stop tracking a parcel |

`/track add` also has a few optional fields:

- **courier:** start typing a name and pick from the list. Leave it empty and Ship24 will guess from the number format. If it guesses wrong, set the courier yourself.
- **label:** a nickname like "Shopee headphones", so the update is easier to recognise.
- **channel:** where to post updates. Defaults to the channel you ran the command in.

## How it works

Every 30 minutes (change it with `POLL_MINUTES`), the bot asks Ship24 about each active parcel and compares the events with the ones it has already seen. New events are posted as an embed and mention you. If nothing is new, it stays quiet.

If the bot can't post in the chosen channel any more (deleted, permissions changed), it falls back to DMing you.

Ship24 only updates when the courier does, so don't expect a faster pace than the courier's own tracking.

## Privacy

The bot is self-hosted, so the only outside service that sees your tracking numbers is Ship24. Your Discord user and channel IDs stay in your own database. Discord itself still sees the commands and messages, since that's where the bot lives.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISCORD_TOKEN` | required | Your bot token |
| `SHIP24_API_KEY` | required | Your Ship24 API key |
| `POLL_MINUTES` | `30` | How often to check for updates |
| `DB_PATH` | `/data/tracker.db` | Where the SQLite database is stored |

## Running without Docker

You'll need Python 3.12 or newer.

```bash
pip install -r requirements.txt
export DISCORD_TOKEN=... SHIP24_API_KEY=... DB_PATH=./tracker.db
python bot.py
```

## Troubleshooting

**Slash commands don't show up.** They're synced when the bot starts. Restart it and give Discord a minute. Make sure the bot was invited with the `applications.commands` scope.

**"Ship24 error" when adding a parcel.** The message includes Ship24's response. The usual causes are a wrong API key, a typo in the number, or hitting the free tier limit.

**No events after adding.** Brand new parcels often have nothing to show yet. The bot will post as soon as the courier scans something.

**The courier dropdown is empty.** The courier list is loaded when the bot starts. Check the logs for a failed request to Ship24.

**Wrong courier detected.** Remove the parcel and add it again with the `courier` field filled in.

## Limits

- The free Ship24 plan allows 10 shipments a month.
- Courier coverage depends on Ship24. Test with a real tracking number from each courier you rely on.
- Polling is simple and reliable but not instant. Ship24 supports webhooks if you ever want real-time updates.