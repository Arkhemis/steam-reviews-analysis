WITH by_language AS (

    SELECT
        app_id,
        COALESCE(language, 'unknown') AS language,
        COUNT(*) AS total_reviews,
        SUM(CASE WHEN voted_up THEN 1 ELSE 0 END) AS total_positive
    FROM {{ ref('steam_review') }}
    GROUP BY 1, 2

)

SELECT
    app_id,
    language,
    total_reviews,
    total_positive,
    ROUND(total_positive::numeric / total_reviews, 4) AS pct_positive,
    ROUND(
        total_reviews::numeric / SUM(total_reviews) OVER (PARTITION BY app_id), 4
    ) AS pct_of_total

FROM by_language
