WITH by_language AS (

    SELECT
        language,
        SUM(total_reviews) AS total_reviews,
        SUM(total_positive) AS total_positive
    FROM {{ ref('language_review_score') }}
    GROUP BY 1

)

SELECT
    language,
    total_reviews,
    total_positive,
    ROUND(total_positive::numeric / total_reviews, 4) AS pct_positive,
    ROUND(total_reviews::numeric / SUM(total_reviews) OVER (), 4) AS pct_of_total

FROM by_language
