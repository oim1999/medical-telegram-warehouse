-- tests/assert_no_future_messages.sql
-- ─────────────────────────────────────
-- Custom data test: ensures no messages have a date in the future.
-- A future message_date indicates a data quality issue in the scraper
-- or a timezone handling error.
--
-- This query MUST return 0 rows to pass.

select
    message_id,
    channel_name,
    message_date,
    current_timestamp as check_time
from {{ ref('stg_telegram_messages') }}
where
    message_date is not null
    and message_date > current_timestamp
