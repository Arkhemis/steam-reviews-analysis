{{ config(order_by='(window_name, app_id)') }}

-- Ancrées sur la dernière date ingérée : l'ingestion peut prendre du retard.
WITH bounds AS (

    SELECT max(review_date) AS latest
    FROM {{ ref('game_review_trend_daily') }}

),

windows AS (

    SELECT
        'week' AS window_name,
        latest - 6 AS starts_on,
        latest AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'previous_week' AS window_name,
        latest - 13 AS starts_on,
        latest - 7 AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'month' AS window_name,
        latest - 29 AS starts_on,
        latest AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'previous_month' AS window_name,
        latest - 59 AS starts_on,
        latest - 30 AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'year_to_date' AS window_name,
        toStartOfYear(latest) AS starts_on,
        latest AS ends_on
    FROM bounds

)

SELECT
    w.window_name,
    t.app_id,
    w.starts_on,
    w.ends_on,
    sum(t.total_reviews) AS total_reviews,
    sum(t.total_positive) AS total_positive,
    round(
        sum(t.total_positive) / nullIf(sum(t.total_reviews), 0),
        4
    ) AS pct_positive
-- Cinq fenêtres : un produit filtré, faute de jointure sur une inégalité seule.
FROM {{ ref('game_review_trend_daily') }} AS t
CROSS JOIN windows AS w
WHERE t.review_date BETWEEN w.starts_on AND w.ends_on
GROUP BY w.window_name, t.app_id, w.starts_on, w.ends_on
