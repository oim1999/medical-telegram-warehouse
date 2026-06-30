"""
scripts/load_yolo_results.py
------------------------------
Loads the YOLOv8 detection CSV (data/processed/yolo_detections.csv)
into a raw.image_detections table in PostgreSQL. This table is later
read by the dbt model fct_image_detections.sql.

Usage:
    python scripts/load_yolo_results.py
"""

import os
import csv
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DB_CONFIG = {
    "host":     os.environ.get("POSTGRES_HOST",     "localhost"),
    "port":     int(os.environ.get("POSTGRES_PORT", "5432")),
    "dbname":   os.environ.get("POSTGRES_DB",       "medical_warehouse"),
    "user":     os.environ.get("POSTGRES_USER",     "postgres"),
    "password": os.environ.get("POSTGRES_PASSWORD", "root"),
}

BASE_DIR  = Path(__file__).resolve().parent.parent
CSV_PATH  = BASE_DIR / "data" / "processed" / "yolo_detections.csv"

CREATE_TABLE = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.image_detections (
    id                BIGSERIAL PRIMARY KEY,
    message_id        BIGINT       NOT NULL,
    channel_name      VARCHAR(255) NOT NULL,
    image_path        TEXT,
    detected_class    VARCHAR(100),
    confidence_score  NUMERIC(5,4),
    image_category    VARCHAR(50)  NOT NULL,
    loaded_at         TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_image_detections_message
    ON raw.image_detections(message_id, channel_name);
"""

INSERT_STMT = """
INSERT INTO raw.image_detections
    (message_id, channel_name, image_path, detected_class,
     confidence_score, image_category)
VALUES %s;
"""


def load_csv() -> list[tuple]:
    """Read the YOLO detections CSV and return a list of insert tuples."""
    rows = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((
                int(row["message_id"]),
                row["channel_name"],
                row["image_path"],
                row["detected_class"] or None,
                float(row["confidence_score"]) if row["confidence_score"] else None,
                row["image_category"],
            ))
    return rows


def main():
    if not CSV_PATH.exists():
        logger.error(f"CSV not found at {CSV_PATH}. Run src/yolo_detect.py first.")
        return

    conn = psycopg2.connect(**DB_CONFIG)

    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE)
    conn.commit()
    logger.info("Ensured raw.image_detections table exists.")

    rows = load_csv()
    logger.info(f"Loaded {len(rows)} rows from CSV.")

    if rows:
        with conn.cursor() as cur:
            # Clear previous results before reloading — detection results
            # are reproducible from images, so a full refresh is safe
            # and avoids duplicate accumulation across re-runs.
            cur.execute("TRUNCATE raw.image_detections;")
            execute_values(cur, INSERT_STMT, rows)
        conn.commit()
        logger.info(f"Inserted {len(rows)} detection records into raw.image_detections.")

    conn.close()


if __name__ == "__main__":
    main()
