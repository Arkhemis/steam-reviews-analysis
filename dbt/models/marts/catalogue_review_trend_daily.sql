{{
    config(
        indexes=[
            {'columns': ['review_date'], 'type': 'btree', 'unique': True},
        ]
    )
}}

SELECT
    review_date,
    COUNT(*) AS games_reviewed,
    SUM(total_reviews) AS total_reviews,
    SUM(total_positive) AS total_positive,
    SUM(total_negative) AS total_negative,
    ROUND(
        SUM(total_positive)::numeric / NULLIF(SUM(total_reviews), 0),
        4
    ) AS pct_positive
FROM {{ ref('game_review_trend_daily') }}
GROUP BY review_date
