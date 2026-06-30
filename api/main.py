"""
api/main.py
------------
FastAPI application exposing the medical_warehouse dbt marts as a
REST analytical API. Implements the four required endpoints:

  GET /api/reports/top-products
  GET /api/channels/{channel_name}/activity
  GET /api/search/messages
  GET /api/reports/visual-content

Run with:
    uvicorn api.main:app --reload --port 8000

Interactive docs available at:
    http://localhost:8000/docs
"""

import re
from collections import Counter

from fastapi import FastAPI, Depends, HTTPException, Query, Path as PathParam
from sqlalchemy.orm import Session
from sqlalchemy import text
from loguru import logger

from api.database import get_db
from api.schemas import (
    TopProductsResponse, TopProductItem,
    ChannelActivityResponse, ChannelActivityDay,
    MessageSearchResponse, MessageSearchResult,
    VisualContentResponse, ChannelVisualStats,
)

app = FastAPI(
    title="Medical Telegram Warehouse API",
    description=(
        "Analytical API exposing insights from Ethiopian medical Telegram "
        "channels (CheMed, Lobelia Cosmetics, Tikvah Pharma). Built on a "
        "dbt star schema warehouse."
    ),
    version="1.0.0",
)

# Common English stop words excluded from product term extraction.
# This is intentionally small — the goal is filtering grammatical noise,
# not full NLP stop-word removal.
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "but",
    "for", "with", "from", "to", "in", "on", "at", "of", "this", "that",
    "now", "available", "price", "etb", "birr", "contact", "order",
    "per", "each", "new", "we", "you", "our", "your", "us",
}


# ── Endpoint 1: Top Products ──────────────────────────────────────────────────

@app.get(
    "/api/reports/top-products",
    response_model=TopProductsResponse,
    summary="Most frequently mentioned products/drugs across all channels",
    description=(
        "Tokenizes message_text across all messages, removes common stop "
        "words, and returns the most frequently mentioned terms. Term "
        "matching is case-insensitive and limited to alphabetic tokens "
        "4+ characters long to filter out prices and short noise tokens."
    ),
)
def get_top_products(
    limit: int = Query(10, ge=1, le=100, description="Number of top terms to return."),
    db: Session = Depends(get_db),
):
    try:
        rows = db.execute(text("""
            SELECT message_text, channel_key
            FROM marts.fct_messages
            WHERE message_text IS NOT NULL AND message_text != ''
        """)).fetchall()

        channel_rows = db.execute(text(
            "SELECT channel_key, channel_name FROM marts.dim_channels"
        )).fetchall()
    except Exception as e:
        logger.error(f"Database error in get_top_products: {e}")
        raise HTTPException(status_code=500, detail="Database query failed.")

    channel_map = {r.channel_key: r.channel_name for r in channel_rows}

    term_counts: Counter = Counter()
    term_channels: dict[str, set[str]] = {}

    token_pattern = re.compile(r"[a-zA-Z]{4,}")

    for row in rows:
        tokens = token_pattern.findall(row.message_text.lower())
        channel_name = channel_map.get(row.channel_key, "unknown")
        for token in set(tokens):   # count each term once per message
            if token in STOP_WORDS:
                continue
            term_counts[token] += 1
            term_channels.setdefault(token, set()).add(channel_name)

    top_terms = term_counts.most_common(limit)

    results = [
        TopProductItem(
            term=term,
            mention_count=count,
            channels=sorted(term_channels[term]),
        )
        for term, count in top_terms
    ]

    return TopProductsResponse(limit=limit, results=results)


# ── Endpoint 2: Channel Activity ──────────────────────────────────────────────

@app.get(
    "/api/channels/{channel_name}/activity",
    response_model=ChannelActivityResponse,
    summary="Posting activity and engagement trends for a specific channel",
    responses={404: {"description": "Channel not found"}},
)
def get_channel_activity(
    channel_name: str = PathParam(..., description="Telegram channel username."),
    days: int = Query(30, ge=1, le=365, description="Number of recent days to include in daily_activity."),
    db: Session = Depends(get_db),
):
    try:
        channel_row = db.execute(text("""
            SELECT channel_key, channel_name, channel_type, total_posts,
                   avg_views, avg_forwards, first_post_date, last_post_date
            FROM marts.dim_channels
            WHERE channel_name = :channel_name
        """), {"channel_name": channel_name}).fetchone()
    except Exception as e:
        logger.error(f"Database error in get_channel_activity: {e}")
        raise HTTPException(status_code=500, detail="Database query failed.")

    if channel_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_name}' not found in dim_channels.",
        )

    try:
        daily_rows = db.execute(text("""
            SELECT
                d.full_date,
                COUNT(*) AS message_count,
                SUM(f.view_count) AS total_views,
                SUM(f.forward_count) AS total_forwards
            FROM marts.fct_messages f
            JOIN marts.dim_dates d ON f.date_key = d.date_key
            WHERE f.channel_key = :channel_key
              AND d.full_date >= CURRENT_DATE - (:days || ' days')::interval
            GROUP BY d.full_date
            ORDER BY d.full_date DESC
        """), {"channel_key": channel_row.channel_key, "days": days}).fetchall()
    except Exception as e:
        logger.error(f"Database error fetching daily activity: {e}")
        raise HTTPException(status_code=500, detail="Database query failed.")

    daily_activity = [
        ChannelActivityDay(
            date=row.full_date.isoformat(),
            message_count=row.message_count,
            total_views=int(row.total_views or 0),
            total_forwards=int(row.total_forwards or 0),
        )
        for row in daily_rows
    ]

    return ChannelActivityResponse(
        channel_name=channel_row.channel_name,
        channel_type=channel_row.channel_type,
        total_posts=channel_row.total_posts,
        avg_views=float(channel_row.avg_views or 0),
        avg_forwards=float(channel_row.avg_forwards or 0),
        first_post_date=channel_row.first_post_date,
        last_post_date=channel_row.last_post_date,
        daily_activity=daily_activity,
    )


# ── Endpoint 3: Message Search ────────────────────────────────────────────────

@app.get(
    "/api/search/messages",
    response_model=MessageSearchResponse,
    summary="Search for messages containing a specific keyword",
)
def search_messages(
    query: str = Query(..., min_length=2, description="Keyword to search for (case-insensitive)."),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results to return."),
    db: Session = Depends(get_db),
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query parameter cannot be empty.")

    try:
        count_row = db.execute(text("""
            SELECT COUNT(*) AS total
            FROM marts.fct_messages
            WHERE message_text ILIKE :pattern
        """), {"pattern": f"%{query}%"}).fetchone()

        rows = db.execute(text("""
            SELECT
                f.message_id, c.channel_name, f.message_date,
                f.message_text, f.view_count, f.forward_count, f.has_image
            FROM marts.fct_messages f
            JOIN marts.dim_channels c ON f.channel_key = c.channel_key
            WHERE f.message_text ILIKE :pattern
            ORDER BY f.view_count DESC
            LIMIT :limit
        """), {"pattern": f"%{query}%", "limit": limit}).fetchall()
    except Exception as e:
        logger.error(f"Database error in search_messages: {e}")
        raise HTTPException(status_code=500, detail="Database query failed.")

    results = [
        MessageSearchResult(
            message_id=row.message_id,
            channel_name=row.channel_name,
            message_date=row.message_date,
            message_text=row.message_text,
            view_count=row.view_count,
            forward_count=row.forward_count,
            has_image=row.has_image,
        )
        for row in rows
    ]

    return MessageSearchResponse(
        query=query,
        limit=limit,
        total_matches=count_row.total,
        results=results,
    )


# ── Endpoint 4: Visual Content Stats ──────────────────────────────────────────

@app.get(
    "/api/reports/visual-content",
    response_model=VisualContentResponse,
    summary="Image usage statistics and category breakdown per channel",
    description=(
        "Returns, per channel, the count of images in each YOLO-derived "
        "category (promotional, product_display, lifestyle, other) and "
        "compares average views for messages with vs. without images."
    ),
)
def get_visual_content_stats(db: Session = Depends(get_db)):
    try:
        category_rows = db.execute(text("""
            SELECT
                c.channel_name,
                COUNT(*) FILTER (WHERE d.image_category = 'promotional')      AS promotional_count,
                COUNT(*) FILTER (WHERE d.image_category = 'product_display')  AS product_display_count,
                COUNT(*) FILTER (WHERE d.image_category = 'lifestyle')        AS lifestyle_count,
                COUNT(*) FILTER (WHERE d.image_category = 'other')            AS other_count,
                COUNT(*)                                                      AS total_images
            FROM marts.fct_image_detections d
            JOIN marts.dim_channels c ON d.channel_key = c.channel_key
            GROUP BY c.channel_name
        """)).fetchall()

        engagement_rows = db.execute(text("""
            SELECT
                c.channel_name,
                AVG(f.view_count) FILTER (WHERE f.has_image = true)  AS avg_views_with_image,
                AVG(f.view_count) FILTER (WHERE f.has_image = false) AS avg_views_without_image
            FROM marts.fct_messages f
            JOIN marts.dim_channels c ON f.channel_key = c.channel_key
            GROUP BY c.channel_name
        """)).fetchall()
    except Exception as e:
        logger.error(f"Database error in get_visual_content_stats: {e}")
        raise HTTPException(status_code=500, detail="Database query failed.")

    engagement_map = {r.channel_name: r for r in engagement_rows}

    channels = []
    for row in category_rows:
        eng = engagement_map.get(row.channel_name)
        channels.append(ChannelVisualStats(
            channel_name=row.channel_name,
            total_images=row.total_images,
            promotional_count=row.promotional_count,
            product_display_count=row.product_display_count,
            lifestyle_count=row.lifestyle_count,
            other_count=row.other_count,
            avg_views_with_image=float(eng.avg_views_with_image) if eng and eng.avg_views_with_image else 0.0,
            avg_views_without_image=float(eng.avg_views_without_image) if eng and eng.avg_views_without_image else 0.0,
        ))

    return VisualContentResponse(channels=channels)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/", summary="Health check")
def root():
    return {"status": "ok", "service": "medical-telegram-warehouse-api"}
