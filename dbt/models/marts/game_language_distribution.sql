WITH by_language AS (

    -- payload ->> 'language' can be NULL (no not_null contract on stg_steam_review.language) ;
    -- coalesced so a missing language becomes its own tracked bucket instead of grouping to
    -- NULL, which would silently enter the pct_of_total denominator and fail the not_null test.
    SELECT
        app_id,
        COALESCE(language, 'unknown') AS language,
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
