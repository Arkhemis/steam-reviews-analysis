-- Les tris des fenêtres débordent dès 256 Mo : pic à 1,7 Go au lieu de 2,3.
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
-- Fenêtres enchaînées sur une seule lecture de la staging : ClickHouse recalcule
-- une CTE à chaque référence, et quatre tris en parallèle dépassaient la mémoire.
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

-- Les grossières hors du top, les plus drôles en tête : le rang ne compte que
-- parmi les candidates, isolées dans leur propre partition.
crude AS (

    SELECT
        recommendation_id,
        app_id,
        updated_at,
        language,
        voted_up,
        votes_funny,
        rank_in_game,
        rank_in_game > {{ var('top_n_reviews', 30) }} AND has_profanity AS is_crude_candidate,
        row_number() OVER (
            PARTITION BY app_id, voted_up, language, is_crude_candidate
            ORDER BY votes_funny DESC, rank_in_game ASC
        ) AS crude_rank,
        is_crude_candidate AND crude_rank <= {{ var('top_crude_reviews', 10) }} AS is_crude
    FROM ranked
    WHERE rank_in_game <= {{ var('top_n_reviews', 30) }} OR has_profanity OR votes_funny > 0

),

-- Puis les plus drôles, hors grossières déjà retenues.
funny AS (

    SELECT
        recommendation_id,
        app_id,
        updated_at,
        rank_in_game,
        is_crude,
        rank_in_game > {{ var('top_n_reviews', 30) }} AND votes_funny > 0 AND NOT is_crude
            AS is_funny_candidate,
        row_number() OVER (
            PARTITION BY app_id, voted_up, language, is_funny_candidate
            ORDER BY votes_funny DESC, rank_in_game ASC
        ) AS funny_rank,
        is_funny_candidate AND funny_rank <= {{ var('top_funny_reviews', 10) }} AS is_funny
    FROM crude

)

-- rank_in_game reste le rang d'utilité : les ajouts passent après le top
-- (rang > top_n_reviews) et `pick` dit pourquoi une review est là.
SELECT
    recommendation_id,
    app_id,
    updated_at,
    rank_in_game,
    multiIf(
        rank_in_game <= {{ var('top_n_reviews', 30) }}, 'useful',
        is_crude, 'crude',
        'funny'
    ) AS pick
FROM funny
WHERE rank_in_game <= {{ var('top_n_reviews', 30) }} OR is_crude OR is_funny
