WITH by_language AS (

    -- payload ->> 'language' can be NULL (no not_null contract on stg_steam_review.language) ;
    -- coalesced so a missing language becomes its own tracked bucket instead of grouping to
    -- NULL, which would silently enter the denominators below and fail the not_null tests.
    SELECT
        COALESCE(language, 'unknown') AS language,
        COUNT(*) AS total_reviews,
        SUM(CASE WHEN voted_up THEN 1 ELSE 0 END) AS total_positive
    FROM {{ ref('steam_review') }}
    GROUP BY 1

)

SELECT
    language,
    total_reviews,
    total_positive,
    ROUND(total_positive::numeric / total_reviews, 4) AS pct_positive,
    ROUND(total_reviews::numeric / SUM(total_reviews) OVER (), 4) AS pct_of_total

FROM by_language
