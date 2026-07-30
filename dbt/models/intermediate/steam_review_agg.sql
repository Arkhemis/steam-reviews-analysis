WITH reviews AS (

    SELECT
        app_id,
        author_playtime_forever_minutes,
        primarily_steam_deck,
        refunded
    FROM {{ ref('steam_review') }}

),

aggregated AS (

    SELECT
        app_id AS steam_app_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY author_playtime_forever_minutes
        ) AS median_playtime_forever_minutes,
        AVG(primarily_steam_deck::int) AS pct_primarily_steam_deck,
        AVG(refunded::int) AS pct_refunded

    FROM reviews
    GROUP BY app_id

)

SELECT * FROM aggregated
