-- models/marts/dim_dates.sql
-- ────────────────────────────
-- Date dimension table.
-- Covers the full date range present in the messages plus a buffer.
-- Used as the time spine for all date-based analytics.

{{ config(materialized='table') }}

with date_spine as (
    -- Generate one row per calendar day from the earliest to latest message date
    select
        generate_series(
            (select date_trunc('day', min(message_date))
             from {{ ref('stg_telegram_messages') }}),
            (select date_trunc('day', max(message_date))
             from {{ ref('stg_telegram_messages') }}),
            '1 day'::interval
        )::date as full_date
),

final as (
    select
        -- Surrogate key: integer YYYYMMDD (compact, sortable)
        to_char(full_date, 'YYYYMMDD')::integer         as date_key,

        full_date,

        -- Day components
        extract(day   from full_date)::integer           as day_of_month,
        extract(dow   from full_date)::integer           as day_of_week,   -- 0=Sun, 6=Sat
        to_char(full_date, 'Day')                        as day_name,

        -- Week components
        extract(week  from full_date)::integer           as week_of_year,

        -- Month components
        extract(month from full_date)::integer           as month,
        to_char(full_date, 'Month')                      as month_name,

        -- Quarter
        extract(quarter from full_date)::integer         as quarter,

        -- Year
        extract(year  from full_date)::integer           as year,

        -- Weekend flag
        case
            when extract(dow from full_date) in (0, 6)
            then true else false
        end::boolean                                     as is_weekend

    from date_spine
)

select * from final
