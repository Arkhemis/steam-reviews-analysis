{{ config(order_by='igdb_id') }}

-- Un jeu IGDB peut lier plusieurs éditions Steam : on garde la plus reviewée.
SELECT
    i.igdb_id AS igdb_id,
    i.steam_app_id AS steam_app_id,
    i.name AS game_name,
    i.first_release_date AS first_release_date,
    i.genres AS genres,
    i.developers AS developers,
    i.publishers AS publishers,
    i.cover_url AS cover_url

FROM {{ source('raw', 'igdb_games') }} AS i
LEFT JOIN {{ source('raw', 'steam_review_counts') }} AS c
    ON i.steam_app_id = c.app_id
ORDER BY i.igdb_id ASC, ifNull(c.total_reviews, 0) DESC, i.steam_app_id ASC
LIMIT 1 BY i.igdb_id
