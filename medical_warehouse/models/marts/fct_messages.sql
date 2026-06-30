-- models/marts/fct_messages.sql
-- ──────────────────────────────
-- Central fact table of the star schema.
-- One row per Telegram message, joined to channel and date dimensions.

{{ config(materialized='table') }}

with messages as (
    select * from {{ ref('stg_telegram_messages') }}
),

channels as (
    select * from {{ ref('dim_channels') }}
),

dates as (
    select * from {{ ref('dim_dates') }}
),

final as (
    select
        -- Surrogate key for the fact row
        row_number() over (
            order by m.channel_name, m.message_id
        )                                               as fact_key,

        -- Natural key
        m.message_id,

        -- Foreign keys to dimension tables
        c.channel_key,
        d.date_key,

        -- Message content
        m.message_text,
        m.message_length,

        -- Engagement metrics
        m.view_count,
        m.forward_count,

        -- Media flags
        m.has_media,
        m.has_image,
        m.image_path,

        -- Timestamps (for partitioning / debugging)
        m.message_date,
        m.scraped_at

    from messages m

    -- Join to channel dimension
    left join channels c
        on m.channel_name = c.channel_name

    -- Join to date dimension
    left join dates d
        on d.full_date = m.message_date::date
)

select * from final
