WITH by_language AS (

    SELECT
        app_id,
        language,
        COUNT(*) AS review_count
    FROM {{ ref('steam_review') }}
    GROUP BY 1, 2

)

SELECT
    app_id,
    language,
    review_count,
    ROUND(
        review_count::numeric
        / SUM(review_count) OVER (PARTITION BY app_id),
        4
    ) AS pct_of_total

FROM by_language
