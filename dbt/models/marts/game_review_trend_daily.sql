-- Trié par (app_id, review_date) : le site lit un jeu à la fois.
{{ config(order_by='(app_id, review_date)') }}

SELECT
    app_id,
    toDate(created_at) AS review_date,
    count() AS total_reviews,
    countIf(voted_up) AS total_positive,
    countIf(NOT voted_up) AS total_negative,
    round(countIf(voted_up) / count(), 4) AS pct_positive
FROM {{ ref('steam_review') }}
GROUP BY 1, 2
