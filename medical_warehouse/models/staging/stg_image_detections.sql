-- models/staging/stg_image_detections.sql
-- ──────────────────────────────────────────
-- Staging model: cleans raw YOLOv8 detection results.
--
-- Transformations applied:
--   1. Type casting: confidence_score to consistent NUMERIC
--   2. Deduplication: keeps the highest-confidence detection per
--      (message_id, detected_class) pair — YOLO can fire multiple
--      bounding boxes for the same object class in one image
--   3. Filtering: removes rows with NULL message_id

{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'image_detections') }}
),

cleaned as (
    select
        message_id::bigint                              as message_id,
        trim(channel_name)::varchar(255)                 as channel_name,
        image_path,
        detected_class,
        confidence_score::numeric(5,4)                   as confidence_score,
        image_category::varchar(50)                      as image_category
    from source
    where message_id is not null
),

deduplicated as (
    -- One row per (message_id, detected_class): keep highest confidence
    select *,
        row_number() over (
            partition by message_id, detected_class
            order by confidence_score desc nulls last
        ) as _row_num
    from cleaned
)

select
    message_id,
    channel_name,
    image_path,
    detected_class,
    confidence_score,
    image_category
from deduplicated
where _row_num = 1
