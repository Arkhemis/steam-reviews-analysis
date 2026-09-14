{{
    config(
        indexes=[
            {'columns': ['window_name', 'pct_positive'], 'type': 'btree'},
            {'columns': ['app_id'], 'type': 'btree'},
        ]
    )
}}

-- Les fenêtres sont ancrées sur la dernière date présente dans le modèle
-- source, jamais sur CURRENT_DATE : l'ingestion peut avoir plusieurs jours de
-- retard, et une fenêtre calée sur « aujourd'hui » serait alors vide.
WITH bounds AS (

    SELECT MAX(review_date) AS latest
    FROM {{ ref('game_review_trend_daily') }}

),

windows AS (

    SELECT
        'week' AS window_name,
        (latest - INTERVAL '6 days')::DATE AS starts_on,
        latest AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'month' AS window_name,
        (latest - INTERVAL '29 days')::DATE AS starts_on,
        latest AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'year_to_date' AS window_name,
        DATE_TRUNC('year', latest)::DATE AS starts_on,
        latest AS ends_on
    FROM bounds

)

SELECT
    w.window_name,
    t.app_id,
    w.starts_on,
    w.ends_on,
    SUM(t.total_reviews) AS total_reviews,
    SUM(t.total_positive) AS total_positive,
    ROUND(
        SUM(t.total_positive)::NUMERIC / NULLIF(SUM(t.total_reviews), 0),
        4
    ) AS pct_positive
FROM {{ ref('game_review_trend_daily') }} AS t
INNER JOIN windows AS w
    ON t.review_date BETWEEN w.starts_on AND w.ends_on
GROUP BY w.window_name, t.app_id, w.starts_on, w.ends_on
