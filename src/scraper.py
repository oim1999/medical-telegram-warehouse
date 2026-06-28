"""
src/scraper.py
--------------
Telegram channel scraper for Ethiopian medical business data.
Extracts messages and images from public Telegram channels using Telethon.

Channels targeted:
  - CheMed (@CheMed123)
  - Lobelia Cosmetics (@lobelia4cosmetics)
  - Tikvah Pharma (@tikvahpharma)
  - Additional channels from et.tgstat.com/medicine

Data Lake structure:
  data/raw/telegram_messages/YYYY-MM-DD/{channel_name}.json
  data/raw/images/{channel_name}/{message_id}.jpg

Usage:
    python src/scraper.py [--channels channel1 channel2] [--limit 500]
"""

import os
import json
import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto
from loguru import logger

# ── Load environment ─────────────────────────────────────────────────────────
load_dotenv()

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE    = os.environ.get("TELEGRAM_PHONE", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR / "data" / "raw"
MSGS_DIR    = DATA_DIR / "telegram_messages"
IMGS_DIR    = DATA_DIR / "images"
LOGS_DIR    = BASE_DIR / "logs"
SESSION_DIR = BASE_DIR / ".sessions"

for d in [MSGS_DIR, IMGS_DIR, LOGS_DIR, SESSION_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
log_file = LOGS_DIR / f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logger.add(
    log_file,
    rotation="50 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

# ── Target channels ───────────────────────────────────────────────────────────
DEFAULT_CHANNELS = [
    "CheMed123",                        
    "lobelia4cosmetics",               
    "tikvahpharma",                     
    "medicalequipmentspare",               
    "EAHCI",                           
]


def serialize_message(msg, channel_name: str, image_path: str | None) -> dict:
    """Convert a Telethon Message object to a JSON-serializable dict."""
    return {
        "message_id":   msg.id,
        "channel_name": channel_name,
        "message_date": msg.date.isoformat() if msg.date else None,
        "message_text": msg.text or "",
        "has_media":    msg.media is not None,
        "image_path":   image_path,
        "views":        msg.views or 0,
        "forwards":     msg.forwards or 0,
        "scraped_at":   datetime.now(timezone.utc).isoformat(),
    }


async def download_image(
    client: TelegramClient,
    msg,
    channel_name: str,
) -> str | None:
    """
    Download a photo from a message to the images data lake.
    Returns the relative image path or None if download fails.
    """
    channel_img_dir = IMGS_DIR / channel_name
    channel_img_dir.mkdir(parents=True, exist_ok=True)

    img_path = channel_img_dir / f"{msg.id}.jpg"

    # Skip if already downloaded (idempotent re-runs)
    if img_path.exists():
        logger.debug(f"Image already exists: {img_path}")
        return str(img_path.relative_to(BASE_DIR))

    try:
        await client.download_media(msg, file=str(img_path))
        logger.debug(f"Downloaded image: {img_path}")
        return str(img_path.relative_to(BASE_DIR))
    except Exception as e:
        logger.warning(f"Failed to download image for msg {msg.id}: {e}")
        return None


async def scrape_channel(
    client: TelegramClient,
    channel_username: str,
    limit: int = 500,
) -> list[dict]:
    """
    Scrape all messages (up to `limit`) from a single channel.
    Returns list of message dicts.
    """
    logger.info(f"Starting scrape: @{channel_username} (limit={limit})")
    messages = []

    try:
        entity = await client.get_entity(channel_username)
        channel_name = entity.username or channel_username

        async for msg in client.iter_messages(entity, limit=limit):
            image_path = None

            # Download photo if present
            if msg.media and isinstance(msg.media, MessageMediaPhoto):
                image_path = await download_image(client, msg, channel_name)

            record = serialize_message(msg, channel_name, image_path)
            messages.append(record)

        logger.info(f"Scraped {len(messages)} messages from @{channel_username}")

    except Exception as e:
        logger.error(f"Error scraping @{channel_username}: {e}")

    return messages


def save_to_data_lake(messages: list[dict], channel_name: str) -> None:
    """
    Persist messages as JSON files partitioned by date.
    Path: data/raw/telegram_messages/YYYY-MM-DD/{channel_name}.json
    Each date partition is a list of messages from that day.
    """
    # Group messages by date
    by_date: dict[str, list[dict]] = {}
    for msg in messages:
        if msg["message_date"]:
            date_str = msg["message_date"][:10]   # YYYY-MM-DD
        else:
            date_str = "unknown"
        by_date.setdefault(date_str, []).append(msg)

    # Write one JSON file per (date, channel)
    for date_str, day_msgs in by_date.items():
        partition_dir = MSGS_DIR / date_str
        partition_dir.mkdir(parents=True, exist_ok=True)
        out_file = partition_dir / f"{channel_name}.json"

        # Merge with existing data (idempotent)
        existing: list[dict] = []
        if out_file.exists():
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)

        # Deduplicate by message_id
        existing_ids = {m["message_id"] for m in existing}
        new_msgs = [m for m in day_msgs if m["message_id"] not in existing_ids]
        merged = existing + new_msgs

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(new_msgs)} new messages to {out_file}")


async def run_scraper(channels: list[str], limit: int = 500) -> None:
    """Main scraper coroutine — iterates over all target channels."""
    session_file = SESSION_DIR / "telegram_session"

    async with TelegramClient(str(session_file), API_ID, API_HASH) as client:
        if PHONE:
            await client.start(phone=PHONE)
        else:
            await client.start()

        logger.info(f"Connected to Telegram. Scraping {len(channels)} channel(s).")

        for channel in channels:
            try:
                messages = await scrape_channel(client, channel, limit=limit)
                if messages:
                    save_to_data_lake(messages, channel)
                else:
                    logger.warning(f"No messages returned for @{channel}")
            except Exception as e:
                logger.error(f"Unhandled error for @{channel}: {e}")

    logger.info("Scraping session complete.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape Ethiopian medical Telegram channels."
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        default=DEFAULT_CHANNELS,
        help="Telegram channel usernames to scrape.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of messages per channel (default: 500).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Channels: {args.channels}")
    logger.info(f"Message limit per channel: {args.limit}")
    asyncio.run(run_scraper(args.channels, args.limit))
