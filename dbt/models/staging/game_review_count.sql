SELECT
    app_id AS steam_app_id,
    total_reviews,
    total_positive,
    total_negative,
    review_score,
    review_score_desc,
    checked_at,
    prev_total_reviews,
    last_backfill_at,
    total_reviews_backfilled

FROM {{ source('raw', 'steam_review_counts') }}
