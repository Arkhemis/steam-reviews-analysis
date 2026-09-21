{{
    config(
        indexes=[
            {'columns': ['steam_app_id'], 'type': 'btree'},
            {'columns': ['total_reviews'], 'type': 'btree'},
            {'columns': ['parent_steam_app_id'], 'type': 'btree'},
        ]
    )
}}


SELECT
    i.igdb_id,
    i.steam_app_id,
    i.game_name,
    i.genres,
    i.developers,
    i.publishers,
    i.cover_url,
    i.first_release_date,

    g.parent_steam_app_id,
    g.price_usd,
    g.app_type,
    g.is_free,
    g.is_early_access,
    g.is_coming_soon,
    g.is_available,

    grc.total_reviews,
    ROUND(
        100.0 * grc.total_positive
        / NULLIF(grc.total_reviews, 0),
        1
    ) AS pct_positive_reviews,
    grc.review_score,

    review_agg.median_playtime_forever_minutes,
    ROUND(100.0 * review_agg.pct_primarily_steam_deck, 1) AS pct_primarily_steam_deck,
    ROUND(100.0 * review_agg.pct_refunded, 1) AS pct_refunded

FROM {{ ref('igdb_game') }} AS i
LEFT JOIN {{ ref('game_review_count') }} AS grc
    USING (steam_app_id)
LEFT JOIN {{ ref('steam_review_agg') }} AS review_agg
    ON review_agg.steam_app_id = i.steam_app_id
LEFT JOIN {{ ref('game_detail') }} AS g
    ON i.steam_app_id = g.steam_app_id
