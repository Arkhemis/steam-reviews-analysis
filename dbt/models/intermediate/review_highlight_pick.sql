-- ranked est calculé à chaque lecture, soit quatre tris en parallèle : chacun
-- déborde sur disque dès 256 Mo, sinon ils dépassent ensemble les 3,5 Go du serveur.
{{ config(
    order_by='(app_id, recommendation_id)',
    query_settings={'max_bytes_before_external_sort': 268435456},
) }}

-- Sélection de review_highlight, en table à part : sa jointure avec la staging
-- hache ce top (~9 M lignes), pas les 183 M reviews.

-- Par (jeu, avis, langue) : les top_n_reviews reviews les plus utiles, puis
-- jusqu'à top_crude_reviews reviews grossières et top_funny_reviews parmi les
-- plus drôles, prises hors de ce top. Le duel du site en tire ses répliques :
-- les plus utiles seules sont rarement drôles, et presque jamais grossières.
WITH eligible_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        updated_at,
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
        updated_at,
        language,
        voted_up,
        votes_funny,
        has_profanity,
        row_number() OVER (
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
        updated_at,
        rank_in_game
    FROM (
        SELECT
            recommendation_id,
            app_id,
            updated_at,
            rank_in_game,
            row_number() OVER (
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
        updated_at,
        rank_in_game
    FROM (
        SELECT
            r.recommendation_id,
            r.app_id,
            r.updated_at,
            r.rank_in_game,
            row_number() OVER (
                PARTITION BY r.app_id, r.voted_up, r.language
                ORDER BY r.votes_funny DESC, r.rank_in_game ASC
            ) AS funny_rank
        FROM ranked AS r
        WHERE
            r.rank_in_game > {{ var('top_n_reviews', 30) }}
            AND r.votes_funny > 0
            AND (r.app_id, r.recommendation_id) NOT IN (
                SELECT
                    c.app_id,
                    c.recommendation_id
                FROM crude AS c
            )
    ) AS f
    WHERE funny_rank <= {{ var('top_funny_reviews', 10) }}

),

-- rank_in_game reste le rang d'utilité : les ajouts passent après le top
-- (rang > top_n_reviews) et `pick` dit pourquoi une review est là.
top_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        updated_at,
        rank_in_game,
        'useful' AS pick
    FROM ranked
    WHERE rank_in_game <= {{ var('top_n_reviews', 30) }}

    UNION ALL

    SELECT
        recommendation_id,
        app_id,
        updated_at,
        rank_in_game,
        'crude' AS pick
    FROM crude

    UNION ALL

    SELECT
        recommendation_id,
        app_id,
        updated_at,
        rank_in_game,
        'funny' AS pick
    FROM funny

)

SELECT
    recommendation_id,
    app_id,
    updated_at,
    rank_in_game,
    pick
FROM top_reviews
