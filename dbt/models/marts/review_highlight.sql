{{ config(order_by='(app_id, rank_in_game)') }}

-- Texte et auteur des reviews de review_highlight_pick, par la clé complète de
-- leur version. Le top (~9 M lignes) est la table hachée : la staging défile.
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
    USING (recommendation_id, app_id, updated_at)
