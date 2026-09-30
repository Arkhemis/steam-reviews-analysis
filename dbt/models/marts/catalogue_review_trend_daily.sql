{{ config(order_by='review_date') }}

-- Qualifiées, sinon ClickHouse lit l'alias sum(total_reviews).
SELECT
    t.review_date AS review_date,
    count() AS games_reviewed,
    sum(t.total_reviews) AS total_reviews,
    sum(t.total_positive) AS total_positive,
    sum(t.total_negative) AS total_negative,
    round(
        sum(t.total_positive) / nullIf(sum(t.total_reviews), 0),
        4
    ) AS pct_positive
FROM {{ ref('game_review_trend_daily') }} AS t
GROUP BY t.review_date
