-- models/staging/stg_telegram_messages.sql
-- ─────────────────────────────────────────
-- Staging model: cleans and standardizes raw Telegram message data.
--
-- Transformations applied:
--   1. Type casting: dates to TIMESTAMP, counts to INTEGER
--   2. Column renaming: consistent snake_case naming
--   3. Filtering: removes records with NULL message_id or channel_name
--   4. Computed fields: message_length, has_image flag
--   5. Text cleaning: trim whitespace from text fields

{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'telegram_messages') }}
),

cleaned as (
    select
        -- Primary key
        message_id::bigint                              as message_id,

        -- Channel info
        trim(channel_name)::varchar(255)                as channel_name,

        -- Timestamps
        message_date::timestamp with time zone          as message_date,
        scraped_at::timestamp with time zone            as scraped_at,

        -- Text content
        trim(message_text)                              as message_text,

        -- Computed: message length (chars), null if no text
        case
            when message_text is not null and trim(message_text) != ''
            then length(trim(message_text))
            else 0
        end                                             as message_length,

        -- Media flags
        coalesce(has_media, false)::boolean             as has_media,
        case
            when image_path is not null and image_path != ''
            then true
            else false
        end::boolean                                    as has_image,

        -- Stored image path (if downloaded)
        nullif(trim(image_path), '')                    as image_path,

        -- Engagement metrics (floor at 0 — negative counts are data errors)
        greatest(coalesce(views::integer, 0), 0)        as view_count,
        greatest(coalesce(forwards::integer, 0), 0)     as forward_count

    from source
    where
        -- Remove records without a valid message identifier
        message_id is not null
        and channel_name is not null
        and trim(channel_name) != ''
),

deduplicated as (
    -- Keep the most recently scraped version of each message
    select *,
        row_number() over (
            partition by message_id, channel_name
            order by scraped_at desc
        ) as _row_num
    from cleaned
)

select
    message_id,
    channel_name,
    message_date,
    scraped_at,
    message_text,
    message_length,
    has_media,
    has_image,
    image_path,
    view_count,
    forward_count
from deduplicated
where _row_num = 1
