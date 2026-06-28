"""
scripts/load_raw_to_postgres.py
--------------------------------
Reads raw JSON files from the data lake and loads them into the
raw.telegram_messages table in PostgreSQL.

Usage:
    python scripts/load_raw_to_postgres.py [--date YYYY-MM-DD]
    python scripts/load_raw_to_postgres.py --all

The script is idempotent — it uses ON CONFLICT DO NOTHING to skip
already-loaded records (keyed on message_id + channel_name).
"""

import os
import json
import argparse
from pathlib import Path
from datetime import date, datetime

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from loguru import logger

# ── Environment ───────────────────────────────────────────────────────────────
load_dotenv()

DB_CONFIG = {
    "host":     os.environ.get("POSTGRES_HOST",     "localhost"),
    "port":     int(os.environ.get("POSTGRES_PORT", "5432")),
    "dbname":   os.environ.get("POSTGRES_DB", "medical_warehouse"),
    "user":     os.environ.get("POSTGRES_USER", "postgres"),
    "password": os.environ.get("POSTGRES_PASSWORD", "root"),
}

BASE_DIR  = Path(__file__).resolve().parent.parent
MSGS_DIR  = BASE_DIR / "data" / "raw" / "telegram_messages"
LOGS_DIR  = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logger.add(
    LOGS_DIR / f"loader_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    level="INFO",
    rotation="10 MB",
)

# ── SQL ───────────────────────────────────────────────────────────────────────
CREATE_RAW_TABLE = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.telegram_messages (
    id              BIGSERIAL PRIMARY KEY,
    message_id      BIGINT       NOT NULL,
    channel_name    VARCHAR(255) NOT NULL,
    message_date    TIMESTAMPTZ,
    message_text    TEXT,
    has_media       BOOLEAN      DEFAULT FALSE,
    image_path      TEXT,
    views           INTEGER      DEFAULT 0,
    forwards        INTEGER      DEFAULT 0,
    scraped_at      TIMESTAMPTZ  DEFAULT NOW(),
    CONSTRAINT uq_msg UNIQUE (message_id, channel_name)
);

CREATE INDEX IF NOT EXISTS idx_raw_channel
    ON raw.telegram_messages(channel_name);
CREATE INDEX IF NOT EXISTS idx_raw_date
    ON raw.telegram_messages(message_date);
"""

INSERT_STMT = """
INSERT INTO raw.telegram_messages
    (message_id, channel_name, message_date, message_text,
     has_media, image_path, views, forwards, scraped_at)
VALUES %s
ON CONFLICT (message_id, channel_name) DO NOTHING;
"""


def get_connection():
    """Create and return a psycopg2 connection."""
    return psycopg2.connect(**DB_CONFIG)


def ensure_schema(conn) -> None:
    """Create raw schema and table if they don't exist."""
    with conn.cursor() as cur:
        cur.execute(CREATE_RAW_TABLE)
    conn.commit()
    logger.info("Raw schema and table ensured.")


def load_json_file(filepath: Path) -> list[dict]:
    """Load and return records from a single JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def build_row(record: dict) -> tuple:
    """Convert a JSON record dict into a DB insert tuple."""
    return (
        record.get("message_id"),
        record.get("channel_name"),
        record.get("message_date"),
        record.get("message_text", ""),
        bool(record.get("has_media", False)),
        record.get("image_path"),
        int(record.get("views", 0)),
        int(record.get("forwards", 0)),
        record.get("scraped_at"),
    )


def load_partition(conn, date_str: str) -> int:
    """
    Load all JSON files from a date partition into PostgreSQL.
    Returns total rows inserted.
    """
    partition_dir = MSGS_DIR / date_str
    if not partition_dir.exists():
        logger.warning(f"Partition not found: {partition_dir}")
        return 0

    total_inserted = 0

    for json_file in sorted(partition_dir.glob("*.json")):
        try:
            records = load_json_file(json_file)
            if not records:
                continue

            rows = [build_row(r) for r in records]

            with conn.cursor() as cur:
                execute_values(cur, INSERT_STMT, rows)
            conn.commit()

            inserted = len(rows)  # approximate; actual may be less due to ON CONFLICT
            total_inserted += inserted
            logger.info(
                f"Loaded {inserted} records from {json_file.name} "
                f"(partition: {date_str})"
            )

        except Exception as e:
            conn.rollback()
            logger.error(f"Error loading {json_file}: {e}")

    return total_inserted


def main():
    parser = argparse.ArgumentParser(
        description="Load raw Telegram JSON data into PostgreSQL."
    )
    parser.add_argument(
        "--date",
        help="Load a specific date partition (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Load all available date partitions.",
    )
    args = parser.parse_args()

    conn = get_connection()
    ensure_schema(conn)

    if args.all:
        partitions = sorted(
            [d.name for d in MSGS_DIR.iterdir() if d.is_dir()]
        )
        logger.info(f"Loading all {len(partitions)} partition(s).")
    elif args.date:
        partitions = [args.date]
    else:
        # Default: load today's partition
        partitions = [date.today().isoformat()]

    total = 0
    for partition in partitions:
        n = load_partition(conn, partition)
        total += n

    conn.close()
    logger.info(f"Done. Total records processed: {total}")


if __name__ == "__main__":
    main()
