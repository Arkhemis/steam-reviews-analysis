{{
    config(
        indexes=[
            {'columns': ['review_date'], 'type': 'btree'},
            {'columns': ['app_id'], 'type': 'btree'},
        ]
    )
}}

SELECT
    app_id,
    DATE(created_at) AS review_date,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN voted_up THEN 1 ELSE 0 END) AS total_positive,
    SUM(CASE WHEN NOT voted_up THEN 1 ELSE 0 END) AS total_negative,
    ROUND(SUM(CASE WHEN voted_up THEN 1 ELSE 0 END)::numeric / COUNT(*), 4) AS pct_positive
FROM {{ ref('steam_review') }}
GROUP BY 1, 2
