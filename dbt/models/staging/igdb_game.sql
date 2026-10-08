{{ config(order_by='igdb_id') }}

-- Un jeu IGDB peut lier plusieurs éditions Steam : on garde la plus reviewée.
SELECT
    i.igdb_id AS igdb_id,
    i.steam_app_id AS steam_app_id,
    i.name AS game_name,
    i.alternative_names AS alternative_names,
    i.first_release_date AS first_release_date,
    i.game_type AS game_type,
    i.game_status AS game_status,
    i.genres AS genres,
    i.themes AS themes,
    i.game_modes AS game_modes,
    i.player_perspectives AS player_perspectives,
    i.game_engines AS game_engines,
    i.developers AS developers,
    i.publishers AS publishers,
    i.porting_companies AS porting_companies,
    i.supporting_companies AS supporting_companies,
    i.developer_countries AS developer_countries,
    i.parent_companies AS parent_companies,
    i.cover_url AS cover_url

FROM {{ source('raw', 'igdb_games') }} AS i
LEFT JOIN {{ source('raw', 'steam_review_counts') }} AS c
    ON i.steam_app_id = c.app_id
ORDER BY i.igdb_id ASC, ifNull(c.total_reviews, 0) DESC, i.steam_app_id ASC
LIMIT 1 BY i.igdb_id
