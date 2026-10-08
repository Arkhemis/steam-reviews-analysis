{{ config(order_by='steam_app_id') }}


SELECT
    i.igdb_id,
    i.steam_app_id AS steam_app_id,
    i.game_name,
    i.alternative_names,
    i.game_type,
    i.game_status,
    i.genres,
    i.themes,
    i.game_modes,
    i.player_perspectives,
    i.game_engines,
    i.developers,
    i.publishers,
    i.porting_companies,
    i.supporting_companies,
    i.developer_countries,
    i.parent_companies,
    i.cover_url,
    i.first_release_date,

    g.parent_steam_app_id,
    g.price_usd,
    g.app_type,
    g.is_free,
    g.is_early_access,
    g.is_coming_soon,
    g.is_available,
    ifNull(grc.is_delisted, false) AS is_delisted,

    grc.total_reviews,
    round(
        100 * grc.total_positive
        / nullIf(grc.total_reviews, 0),
        1
    ) AS pct_positive_reviews,
    grc.review_score,

    review_agg.median_playtime_forever_minutes,
    round(100 * review_agg.pct_primarily_steam_deck, 1) AS pct_primarily_steam_deck,
    round(100 * review_agg.pct_refunded, 1) AS pct_refunded

FROM {{ ref('igdb_game') }} AS i
LEFT JOIN {{ ref('game_review_count') }} AS grc
    USING (steam_app_id)
LEFT JOIN {{ ref('steam_review_agg') }} AS review_agg
    USING (steam_app_id)
LEFT JOIN {{ ref('game_detail') }} AS g
    USING (steam_app_id)
