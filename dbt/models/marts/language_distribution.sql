WITH by_language AS (

    SELECT
        language,
        SUM(review_count) AS review_count
    FROM {{ ref('game_language_distribution') }}
    GROUP BY 1

)

SELECT
    language,
    review_count,
    ROUND(
        review_count::numeric / SUM(review_count) OVER (),
        4
    ) AS pct_of_total

FROM by_language
