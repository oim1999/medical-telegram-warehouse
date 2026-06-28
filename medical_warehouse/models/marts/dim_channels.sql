-- models/marts/dim_channels.sql
-- ──────────────────────────────
-- Dimension table: one row per Telegram channel.
-- Provides channel metadata and summary statistics for analysis.

{{ config(materialized='table') }}

with messages as (
    select * from {{ ref('stg_telegram_messages') }}
),

channel_stats as (
    select
        channel_name,
        min(message_date)                   as first_post_date,
        max(message_date)                   as last_post_date,
        count(*)                            as total_posts,
        round(avg(view_count)::numeric, 2)  as avg_views,
        round(avg(forward_count)::numeric, 2) as avg_forwards,
        sum(case when has_image then 1 else 0 end) as total_images
    from messages
    group by channel_name
),

final as (
    select
        -- Surrogate key: stable integer per channel
        row_number() over (order by channel_name) as channel_key,

        cs.channel_name,

        -- Business classification based on known channel names
        case
            when lower(cs.channel_name) like '%chem%'
                or lower(cs.channel_name) like '%medical%'
                then 'Medical'
            when lower(cs.channel_name) like '%lobelia%'
                or lower(cs.channel_name) like '%cosmet%'
                then 'Cosmetics'
            when lower(cs.channel_name) like '%pharma%'
                or lower(cs.channel_name) like '%tikv%'
                then 'Pharmaceutical'
            else 'Other'
        end                                 as channel_type,

        cs.first_post_date,
        cs.last_post_date,
        cs.total_posts,
        cs.avg_views,
        cs.avg_forwards,
        cs.total_images

    from channel_stats cs
)

select * from final
