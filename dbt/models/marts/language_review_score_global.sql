{{ config(order_by='language') }}

WITH by_language AS (

    SELECT
        language,
        sum(total_reviews) AS total_reviews,
        sum(total_positive) AS total_positive
    FROM {{ ref('language_review_score') }}
    GROUP BY 1

)

SELECT
    language,
    total_reviews,
    total_positive,
    round(total_positive / total_reviews, 4) AS pct_positive,
    round(total_reviews / sum(total_reviews) OVER (), 4) AS pct_of_total

FROM by_language
