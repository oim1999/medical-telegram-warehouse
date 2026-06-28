-- tests/assert_no_empty_channel_names.sql
-- ─────────────────────────────────────────
-- Custom data test: ensures no messages have an empty or whitespace-only
-- channel_name. An empty channel_name breaks all dimension joins.
--
-- This query MUST return 0 rows to pass.

select
    message_id,
    channel_name,
    message_date
from {{ ref('stg_telegram_messages') }}
where
    channel_name is null
    or trim(channel_name) = ''
