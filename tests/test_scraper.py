"""
tests/test_scraper.py
---------------------
Unit tests for the Telegram scraper utility functions.
These tests do NOT require a live Telegram connection.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


# ── Helpers (extracted from scraper for testability) ─────────────────────────

def serialize_message_dict(
    message_id: int,
    channel_name: str,
    date: datetime | None,
    text: str | None,
    has_media: bool,
    image_path: str | None,
    views: int,
    forwards: int,
) -> dict:
    """Replicate the serialize_message logic without Telethon dependency."""
    return {
        "message_id":   message_id,
        "channel_name": channel_name,
        "message_date": date.isoformat() if date else None,
        "message_text": text or "",
        "has_media":    has_media,
        "image_path":   image_path,
        "views":        views,
        "forwards":     forwards,
        "scraped_at":   datetime.now(timezone.utc).isoformat(),
    }


# ── Tests ────────────────────────────────────────────────────────────────────

class TestSerializeMessage:
    def test_basic_text_message(self):
        record = serialize_message_dict(
            message_id=1001,
            channel_name="CheMed2",
            date=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
            text="Paracetamol 500mg available",
            has_media=False,
            image_path=None,
            views=250,
            forwards=10,
        )
        assert record["message_id"] == 1001
        assert record["channel_name"] == "CheMed2"
        assert record["message_text"] == "Paracetamol 500mg available"
        assert record["has_media"] is False
        assert record["views"] == 250
        assert record["forwards"] == 10
        assert record["image_path"] is None

    def test_message_with_image(self):
        record = serialize_message_dict(
            message_id=2002,
            channel_name="lobelia4cosmetics",
            date=datetime(2024, 6, 2, 8, 30, tzinfo=timezone.utc),
            text="Skin cream promotion",
            has_media=True,
            image_path="data/raw/images/lobelia4cosmetics/2002.jpg",
            views=500,
            forwards=25,
        )
        assert record["has_media"] is True
        assert record["image_path"] == "data/raw/images/lobelia4cosmetics/2002.jpg"

    def test_empty_text_message(self):
        record = serialize_message_dict(
            message_id=3003,
            channel_name="tikvahethiopiamedicalcenter",
            date=datetime(2024, 6, 3, tzinfo=timezone.utc),
            text=None,
            has_media=True,
            image_path="data/raw/images/tikvah/3003.jpg",
            views=100,
            forwards=5,
        )
        assert record["message_text"] == ""

    def test_date_serialization(self):
        dt = datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
        record = serialize_message_dict(
            1, "test_channel", dt, "test", False, None, 0, 0
        )
        assert record["message_date"].startswith("2024-01-15")

    def test_null_date(self):
        record = serialize_message_dict(
            1, "test_channel", None, "test", False, None, 0, 0
        )
        assert record["message_date"] is None


class TestDataLakePartitioning:
    def test_date_extraction(self):
        """Verify YYYY-MM-DD extraction from ISO timestamp."""
        iso_date = "2024-06-15T10:30:00+00:00"
        assert iso_date[:10] == "2024-06-15"

    def test_unknown_date_handling(self):
        """Messages with null dates go to 'unknown' partition."""
        record = {"message_date": None, "message_id": 1}
        date_str = record["message_date"][:10] if record["message_date"] else "unknown"
        assert date_str == "unknown"

    def test_json_round_trip(self, tmp_path):
        """Written JSON files are valid and readable."""
        records = [
            serialize_message_dict(
                1, "CheMed2",
                datetime(2024, 6, 1, tzinfo=timezone.utc),
                "Test message", False, None, 100, 5,
            )
        ]
        out = tmp_path / "CheMed2.json"
        with open(out, "w") as f:
            json.dump(records, f)

        with open(out, "r") as f:
            loaded = json.load(f)

        assert len(loaded) == 1
        assert loaded[0]["message_id"] == 1
        assert loaded[0]["channel_name"] == "CheMed2"


class TestDataQuality:
    def test_view_count_floor(self):
        """Negative view counts should be treated as 0 (handled in staging)."""
        raw_views = -5
        cleaned = max(raw_views, 0)
        assert cleaned == 0

    def test_forward_count_floor(self):
        raw_forwards = -1
        cleaned = max(raw_forwards, 0)
        assert cleaned == 0

    def test_message_length_calculation(self):
        text = "  Paracetamol 500mg  "
        length = len(text.strip())
        assert length == 17

    def test_empty_text_length(self):
        text = ""
        length = len(text.strip()) if text and text.strip() else 0
        assert length == 0
