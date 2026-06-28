-- tests/assert_positive_views.sql
-- ──────────────────────────────────
-- Custom data test: ensures all view_count values are non-negative.
-- Negative view counts would indicate a scraper error or data corruption.
--
-- This query MUST return 0 rows to pass.

select
    message_id,
    channel_key,
    view_count
from {{ ref('fct_messages') }}
where view_count < 0
