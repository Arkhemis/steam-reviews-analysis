WITH eligible_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        language,
        voted_up,
        votes_up,
        weighted_vote_score
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
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up, language
            ORDER BY weighted_vote_score DESC, votes_up DESC, recommendation_id ASC
        ) AS rank_in_game
    FROM eligible_reviews

),

top_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        rank_in_game
    FROM ranked
    WHERE rank_in_game <= {{ var('top_n_reviews', 30) }}

)

SELECT
    t.rank_in_game,

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
    s.author_last_played_at

FROM top_reviews AS t
INNER JOIN {{ ref('steam_review') }} AS s
    ON
        t.recommendation_id = s.recommendation_id
        AND t.app_id = s.app_id
