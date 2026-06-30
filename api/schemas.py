"""
api/schemas.py
----------------
Pydantic models defining the request and response shapes for every
API endpoint. FastAPI uses these for automatic validation, serialization,
and OpenAPI documentation generation.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Endpoint 1: Top Products ──────────────────────────────────────────────────

class TopProductItem(BaseModel):
    """A single product/term and its mention frequency."""
    term: str = Field(..., description="The product or drug name extracted from messages.")
    mention_count: int = Field(..., description="Number of messages mentioning this term.")
    channels: list[str] = Field(..., description="Channels where this term was mentioned.")


class TopProductsResponse(BaseModel):
    """Response for GET /api/reports/top-products"""
    limit: int = Field(..., description="The limit parameter used for this query.")
    results: list[TopProductItem]


# ── Endpoint 2: Channel Activity ──────────────────────────────────────────────

class ChannelActivityDay(BaseModel):
    """Posting activity for a single calendar day."""
    date: str = Field(..., description="ISO date (YYYY-MM-DD).")
    message_count: int
    total_views: int
    total_forwards: int


class ChannelActivityResponse(BaseModel):
    """Response for GET /api/channels/{channel_name}/activity"""
    channel_name: str
    channel_type: str
    total_posts: int
    avg_views: float
    avg_forwards: float
    first_post_date: Optional[datetime] = None
    last_post_date: Optional[datetime] = None
    daily_activity: list[ChannelActivityDay]


# ── Endpoint 3: Message Search ────────────────────────────────────────────────

class MessageSearchResult(BaseModel):
    """A single matched message."""
    message_id: int
    channel_name: str
    message_date: Optional[datetime] = None
    message_text: str
    view_count: int
    forward_count: int
    has_image: bool


class MessageSearchResponse(BaseModel):
    """Response for GET /api/search/messages"""
    query: str
    limit: int
    total_matches: int
    results: list[MessageSearchResult]


# ── Endpoint 4: Visual Content Stats ──────────────────────────────────────────

class ChannelVisualStats(BaseModel):
    """Visual content breakdown for a single channel."""
    channel_name: str
    total_images: int
    promotional_count: int
    product_display_count: int
    lifestyle_count: int
    other_count: int
    avg_views_with_image: float
    avg_views_without_image: float


class VisualContentResponse(BaseModel):
    """Response for GET /api/reports/visual-content"""
    channels: list[ChannelVisualStats]


# ── Error response ────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response shape returned on 4xx/5xx errors."""
    detail: str
