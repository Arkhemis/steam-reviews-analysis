-- enable_mergejoin : le merge join retrierait des 182 M de lignes larges ==> OOM
{{ config(pre_hook="SET enable_mergejoin = off") }}

WITH contested AS (

    SELECT recommendation_id
    FROM {{ source('raw', 'steam_reviews') }}
    GROUP BY recommendation_id
    HAVING COUNT(*) > 1

),

source_versions AS (

    SELECT s.*
    FROM {{ source('raw', 'steam_reviews') }} AS s
    WHERE
        NOT EXISTS (
            SELECT 1
            FROM contested AS c
            WHERE c.recommendation_id = s.recommendation_id
        )

    UNION ALL

    (
        SELECT DISTINCT ON (s.recommendation_id) s.*
        FROM {{ source('raw', 'steam_reviews') }} AS s
        INNER JOIN contested AS c ON c.recommendation_id = s.recommendation_id
        ORDER BY s.recommendation_id ASC, s.timestamp_updated DESC, s.loaded_at DESC
    )

),

renamed AS (

    SELECT
        recommendation_id,
        app_id,

        (payload -> 'author' ->> 'steamid')::bigint AS author_steamid,
        payload -> 'author' ->> 'personaname' AS author_personaname,
        payload -> 'author' ->> 'profile_url' AS author_profile_url,
        payload -> 'author' ->> 'avatar' AS author_avatar,
        payload -> 'author' ->> 'persona_status' AS author_persona_status,
        (payload -> 'author' ->> 'num_games_owned')::int AS author_num_games_owned,
        (payload -> 'author' ->> 'num_reviews')::int AS author_num_reviews,

        -- playtimes Steam sont exprimés en minutes
        (payload -> 'author' ->> 'playtime_forever')::int AS author_playtime_forever_minutes,
        (payload -> 'author' ->> 'playtime_at_review')::int AS author_playtime_at_review_minutes,
        (payload -> 'author' ->> 'playtime_last_two_weeks')::int AS author_playtime_last_two_weeks_minutes,
        TO_TIMESTAMP((payload -> 'author' ->> 'last_played')::bigint) AS author_last_played_at,

        payload ->> 'review' AS review_text,
        payload ->> 'language' AS language,
        (payload ->> 'voted_up')::boolean AS voted_up,
        (payload ->> 'votes_up')::int AS votes_up,

        -- l'API Steam sérialise parfois votes_funny comme un uint32 :
        -- une valeur négative comme -1 devient 4294967295, ce qui dépasse un int4 Postgres
        CASE
            WHEN (payload ->> 'votes_funny')::bigint > 2147483647
                THEN (payload ->> 'votes_funny')::bigint - 4294967296
            ELSE (payload ->> 'votes_funny')::bigint
        END::int AS votes_funny,
        (payload ->> 'weighted_vote_score')::numeric AS weighted_vote_score,
        (payload ->> 'comment_count')::int AS comment_count,
        (payload ->> 'steam_purchase')::boolean AS steam_purchase,
        (payload ->> 'received_for_free')::boolean AS received_for_free,
        (payload ->> 'written_during_early_access')::boolean AS written_during_early_access,
        (payload ->> 'primarily_steam_deck')::boolean AS primarily_steam_deck,
        (payload ->> 'refunded')::boolean AS refunded,

        TO_TIMESTAMP((payload ->> 'app_release_date')::double precision) AS app_release_date,
        payload -> 'reactions' AS reactions,

        TO_TIMESTAMP(timestamp_created) AS created_at,
        TO_TIMESTAMP(timestamp_updated) AS updated_at,
        loaded_at

    FROM source_versions

)

SELECT
    *,

    -- attributs dérivés de review_text, matérialisés ici 
    -- afin d'éviter de décompresser encore en aval
    LENGTH(review_text) AS review_text_length,
    COALESCE(review_text ~ '[✅☐]', FALSE) AS is_generic

FROM renamed
