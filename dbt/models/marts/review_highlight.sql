{{
    config(
        pre_hook="SET work_mem = '768MB'",
        indexes=[
            {'columns': ['app_id'], 'type': 'btree'},
            {'columns': ['rank_in_game', 'voted_up'], 'type': 'btree'},
        ]
    )
}}

-- Texte et auteur des reviews de review_highlight_pick, par la clé complète de leur
-- version : pas de registre à relire. Le hash du top (~9 M lignes, ~800 Mo) doit
-- tenir en mémoire, sinon les lots écrivent versions sur disque (> temp_file_limit).
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

FROM {{ ref('review_highlight_pick') }} AS t
INNER JOIN {{ ref('steam_review_versions') }} AS s
    USING (recommendation_id, app_id, updated_at)
