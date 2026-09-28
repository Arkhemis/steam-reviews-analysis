{{ config(order_by='steam_app_id') }}

WITH reviews AS (

    SELECT
        app_id,
        author_playtime_forever_minutes,
        primarily_steam_deck,
        refunded
    FROM {{ ref('steam_review') }}

),

aggregated AS (

    -- quantileExactInclusive interpole comme PERCENTILE_CONT.
    SELECT
        app_id AS steam_app_id,
        quantileExactInclusive(0.5)(author_playtime_forever_minutes)  -- noqa: LT01
            AS median_playtime_forever_minutes,
        avg(toUInt8(primarily_steam_deck)) AS pct_primarily_steam_deck,
        avg(toUInt8(refunded)) AS pct_refunded

    FROM reviews
    GROUP BY app_id

)

SELECT * FROM aggregated
