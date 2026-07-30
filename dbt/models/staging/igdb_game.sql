SELECT
    igdb_id,
    steam_app_id,
    name AS game_name,
    first_release_date,
    genres,
    developers,
    publishers,
    cover_url

FROM {{ source('raw', 'igdb_games') }}
