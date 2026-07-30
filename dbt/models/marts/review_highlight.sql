WITH ranked AS (
    SELECT
        recommendation_id,
        app_id,
        review_text,
        language,

        voted_up,
        votes_up,
        votes_funny,
        weighted_vote_score,

        author_personaname,
        author_avatar,
        author_profile_url,
        author_playtime_at_review_minutes,
        author_last_played_at,
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up
            ORDER BY weighted_vote_score DESC, votes_up DESC, recommendation_id
        ) AS rank_in_game
    FROM {{ ref('steam_review') }}
    WHERE
        review_text IS NOT NULL AND review_text != ''
        AND NOT (review_text LIKE '%✅%' OR review_text LIKE '%☐%')
)

SELECT *
FROM ranked
WHERE rank_in_game <= {{ var('top_n_reviews', 5) }}
-- 
