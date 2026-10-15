-- Deux threads : chaque bloc inséré porte les textes des reviews.
-- Fusion sur la clé de tri commune : ni table de hachage ni débordement de la staging.
{{ config(
    order_by='(app_id, rank_in_game)',
    query_settings={'max_threads': 2, 'join_algorithm': 'full_sorting_merge'},
) }}

-- updated_at hors du USING, sinon la staging est retriée en entier.
SELECT
    t.rank_in_game,
    t.pick,

    s.recommendation_id AS recommendation_id,
    s.app_id AS app_id,
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

FROM {{ ref('steam_review') }} AS s
INNER JOIN {{ ref('review_highlight_pick') }} AS t
    USING (app_id, recommendation_id)
WHERE s.updated_at = t.updated_at
