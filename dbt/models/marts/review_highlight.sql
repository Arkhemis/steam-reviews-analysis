{{
    config(
        pre_hook="SET work_mem = '1GB'; SET hash_mem_multiplier = 16",
        indexes=[
            {'columns': ['app_id'], 'type': 'btree'},
            {'columns': ['rank_in_game', 'voted_up'], 'type': 'btree'},
        ]
    )
}}

-- Par (jeu, avis, langue) : les top_n_reviews reviews les plus utiles, puis
-- jusqu'à top_crude_reviews reviews grossières et top_funny_reviews parmi les
-- plus drôles, prises hors de ce top. Le duel du site en tire ses répliques :
-- les plus utiles seules sont rarement drôles, et presque jamais grossières.
WITH eligible_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        language,
        voted_up,
        votes_up,
        votes_funny,
        weighted_vote_score,
        has_profanity
    FROM {{ ref('steam_review') }}
    WHERE
        author_playtime_at_review_minutes > 120
        AND review_text_length > {{ var('min_review_length', 20) }}
        AND NOT is_generic

),

ranked AS (

    SELECT
        recommendation_id,
        app_id,
        language,
        voted_up,
        votes_funny,
        has_profanity,
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up, language
            ORDER BY weighted_vote_score DESC, votes_up DESC, recommendation_id ASC
        ) AS rank_in_game
    FROM eligible_reviews

),

-- Les grossières d'abord, les plus drôles en tête.
crude AS (

    SELECT
        recommendation_id,
        app_id,
        rank_in_game
    FROM (
        SELECT
            recommendation_id,
            app_id,
            rank_in_game,
            ROW_NUMBER() OVER (
                PARTITION BY app_id, voted_up, language
                ORDER BY votes_funny DESC, rank_in_game ASC
            ) AS crude_rank
        FROM ranked
        WHERE rank_in_game > {{ var('top_n_reviews', 30) }} AND has_profanity
    ) AS c
    WHERE crude_rank <= {{ var('top_crude_reviews', 10) }}

),

-- Puis les plus drôles, hors grossières déjà retenues.
funny AS (

    SELECT
        recommendation_id,
        app_id,
        rank_in_game
    FROM (
        SELECT
            r.recommendation_id,
            r.app_id,
            r.rank_in_game,
            ROW_NUMBER() OVER (
                PARTITION BY r.app_id, r.voted_up, r.language
                ORDER BY r.votes_funny DESC, r.rank_in_game ASC
            ) AS funny_rank
        FROM ranked AS r
        LEFT JOIN crude AS c ON c.recommendation_id = r.recommendation_id
        WHERE
            r.rank_in_game > {{ var('top_n_reviews', 30) }}
            AND r.votes_funny > 0
            AND c.recommendation_id IS NULL
    ) AS f
    WHERE funny_rank <= {{ var('top_funny_reviews', 10) }}

),

-- rank_in_game reste le rang d'utilité : les ajouts passent après le top
-- (rang > top_n_reviews) et `pick` dit pourquoi une review est là.
top_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        rank_in_game,
        'useful' AS pick
    FROM ranked
    WHERE rank_in_game <= {{ var('top_n_reviews', 30) }}

    UNION ALL

    SELECT
        recommendation_id,
        app_id,
        rank_in_game,
        'crude' AS pick
    FROM crude

    UNION ALL

    SELECT
        recommendation_id,
        app_id,
        rank_in_game,
        'funny' AS pick
    FROM funny

)

SELECT
    t.rank_in_game,
    t.pick,

    s.recommendation_id,
    s.app_id,
    s.review_text,
    s.language,

    s.voted_up,
    s.votes_up,
    s.votes_funny,
    s.weighted_vote_score,

    s.author_personaname,
    s.author_avatar,
    s.author_profile_url,
    s.author_playtime_at_review_minutes,
    s.author_last_played_at,

    s.created_at

FROM top_reviews AS t
INNER JOIN {{ ref('steam_review') }} AS s
    USING (recommendation_id, app_id)
