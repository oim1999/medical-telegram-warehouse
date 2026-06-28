#!/usr/bin/env python3
"""
scripts/setup_database.py
--------------------------
One-time database setup script. Run this ONCE after starting Docker
to create the database, schemas, and raw table.

This script connects to the 'postgres' default database first (which
always exists), creates 'medical_warehouse' if it doesn't exist, then
connects to it to create schemas and tables.

Usage:
    python scripts/setup_database.py

Why this script exists:
    PostgreSQL's 'CREATE DATABASE' cannot run inside a transaction block,
    so it cannot be part of a regular SQL script. This Python script handles
    that correctly by using autocommit mode for the CREATE DATABASE step.
"""

import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

load_dotenv()

# ── Connection config ─────────────────────────────────────────────────────────
HOST     = os.environ.get("POSTGRES_HOST",     "localhost")
PORT     = int(os.environ.get("POSTGRES_PORT", "5432"))
USER     = os.environ.get("POSTGRES_USER",     "postgres")
PASSWORD = os.environ.get("POSTGRES_PASSWORD", "root")
DB_NAME  = os.environ.get("POSTGRES_DB",       "medical_warehouse")


def create_database():
    """
    Connect to the default 'postgres' database and create medical_warehouse
    if it doesn't already exist.

    KEY DETAIL: CREATE DATABASE requires autocommit=True because PostgreSQL
    does not allow database creation inside a transaction block.
    Attempting it inside a transaction raises:
        "ERROR: CREATE DATABASE cannot run inside a transaction block"
    """
    print(f"Connecting to PostgreSQL at {HOST}:{PORT} as '{USER}'...")

    # Step 1: Connect to the 'postgres' system database (always exists)
    conn = psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD,
        dbname="postgres"   # <-- connect to default DB, not our target
    )

    # Step 2: Enable autocommit — required for CREATE DATABASE
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    with conn.cursor() as cur:
        # Step 3: Check if database already exists
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (DB_NAME,)
        )
        exists = cur.fetchone()

        if exists:
            print(f"✓ Database '{DB_NAME}' already exists — skipping creation.")
        else:
            cur.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"✓ Database '{DB_NAME}' created successfully.")

    conn.close()


def create_schemas_and_tables():
    """
    Connect to the medical_warehouse database and create the required
    schemas (raw, staging, marts) and the raw.telegram_messages table.
    """
    conn = psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD,
        dbname=DB_NAME
    )

    ddl = """
    -- Create schemas
    CREATE SCHEMA IF NOT EXISTS raw;
    CREATE SCHEMA IF NOT EXISTS staging;
    CREATE SCHEMA IF NOT EXISTS marts;

    -- Raw messages table
    CREATE TABLE IF NOT EXISTS raw.telegram_messages (
        id              BIGSERIAL    PRIMARY KEY,
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

    -- Indexes for performance
    CREATE INDEX IF NOT EXISTS idx_raw_channel
        ON raw.telegram_messages(channel_name);

    CREATE INDEX IF NOT EXISTS idx_raw_date
        ON raw.telegram_messages(message_date);
    """

    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    conn.close()

    print("✓ Schemas created: raw, staging, marts")
    print("✓ Table created: raw.telegram_messages")
    print("✓ Indexes created on channel_name and message_date")


def verify_setup():
    """Connect and confirm everything is accessible."""
    conn = psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD,
        dbname=DB_NAME
    )
    with conn.cursor() as cur:
        cur.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name IN ('raw', 'staging', 'marts')
            ORDER BY schema_name
        """)
        schemas = [row[0] for row in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'raw'
              AND table_name = 'telegram_messages'
        """)
        table_exists = cur.fetchone()[0]

    conn.close()

    print(f"\n── Verification ────────────────────────────────")
    print(f"  Database : {DB_NAME}")
    print(f"  Schemas  : {schemas}")
    print(f"  raw.telegram_messages : {'EXISTS ✓' if table_exists else 'MISSING ✗'}")

    if len(schemas) < 3 or not table_exists:
        print("\n✗ Setup incomplete. Check errors above.")
        sys.exit(1)
    else:
        print("\n✓ Database setup complete. You can now run:")
        print("  python scripts/load_raw_to_postgres.py --all")
        print("  cd medical_warehouse && dbt run")


if __name__ == "__main__":
    try:
        create_database()
        create_schemas_and_tables()
        verify_setup()
    except psycopg2.OperationalError as e:
        print(f"\n✗ Cannot connect to PostgreSQL: {e}")
        print("\nTroubleshooting:")
        print("  1. Is Docker running?  →  docker compose ps")
        print("  2. Is the container up?  →  docker compose up -d")
        print("  3. Are your .env credentials correct?")
        print(f"     HOST={HOST}, PORT={PORT}, USER={USER}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)
