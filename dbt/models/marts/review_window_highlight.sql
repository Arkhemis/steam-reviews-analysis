{{ config(order_by='(window_name, category, language, rank)') }}

-- Ancrées sur la dernière date ingérée, comme game_window_score.
WITH bounds AS (

    SELECT max(review_date) AS latest
    FROM {{ ref('game_review_trend_daily') }}

),

windows AS (

    SELECT
        'week' AS window_name,
        latest - 6 AS starts_on,
        latest AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'month' AS window_name,
        latest - 29 AS starts_on,
        latest AS ends_on
    FROM bounds

),

-- Une seule lecture pour les deux fenêtres ; le texte n'est lu que pour les lauréats.
recent_reviews AS (

    SELECT
        recommendation_id,
        app_id,
        language,
        votes_up,
        votes_funny,
        weighted_vote_score,
        created_at
    FROM {{ ref('steam_review') }}
    WHERE
        created_at >= (SELECT b.latest - 29 FROM bounds AS b)
        AND review_text_length > {{ var('min_review_length', 20) }}
        AND NOT is_generic
        AND language IS NOT NULL

        -- Écarte aussi les votes_funny négatifs (uint32 de l'API).
        AND (votes_funny > 0 OR votes_up > 0)

),

candidates AS (

    SELECT
        w.window_name AS window_name,
        r.category AS category,
        r.language AS language,
        r.app_id AS app_id,
        r.recommendation_id AS recommendation_id,
        r.votes_up AS votes_up,

        if(
            r.category = 'funny',
            toDecimal128(r.votes_funny, 20),
            r.weighted_vote_score
        ) AS primary_score

    FROM (
        SELECT
            *,
            arrayJoin(['funny', 'helpful']) AS category
        FROM recent_reviews
    ) AS r
    CROSS JOIN windows AS w
    WHERE
        toDate(r.created_at) BETWEEN w.starts_on AND w.ends_on
        AND (
            (r.category = 'funny' AND r.votes_funny > 0)
            OR (r.category = 'helpful' AND r.votes_up > 0)
        )

),

-- Une review par jeu, sinon un jeu très commenté prend tout le podium.
best_per_game AS (

    SELECT
        window_name,
        category,
        language,
        app_id,
        recommendation_id,
        votes_up,
        primary_score
    FROM (
        SELECT
            window_name,
            category,
            language,
            app_id,
            recommendation_id,
            votes_up,
            primary_score,
            row_number() OVER (
                PARTITION BY window_name, category, language, app_id
                ORDER BY primary_score DESC, votes_up DESC, recommendation_id ASC
            ) AS rank_in_game
        FROM candidates
    ) AS ranked_in_game
    WHERE rank_in_game = 1

),

ranked AS (

    SELECT
        window_name,
        category,
        language,
        app_id,
        recommendation_id,
        rank
    FROM (
        SELECT
            window_name,
            category,
            language,
            app_id,
            recommendation_id,
            row_number() OVER (
                PARTITION BY window_name, category, language
                ORDER BY primary_score DESC, votes_up DESC, recommendation_id ASC
            ) AS rank
        FROM best_per_game
    ) AS ranked_games
    WHERE rank <= {{ var('top_n_window_reviews', 5) }}

),

-- IN sur la clé de tri : seules les granules des lauréats sont lues.
winners AS (

    SELECT
        recommendation_id,
        app_id,
        review_text,
        voted_up,
        votes_up,
        votes_funny,
        weighted_vote_score,
        author_personaname,
        author_avatar,
        author_playtime_at_review_minutes,
        created_at
    FROM {{ ref('steam_review') }}
    WHERE
        (app_id, recommendation_id) IN (
            SELECT
                k.app_id,
                k.recommendation_id
            FROM ranked AS k
        )

)

SELECT
    k.window_name AS window_name,
    k.category,
    k.language,
    toInt32(k.rank) AS rank,
    w.starts_on,
    w.ends_on,

    r.recommendation_id AS recommendation_id,
    r.app_id AS app_id,
    r.review_text,

    r.voted_up,
    r.votes_up,
    r.votes_funny,
    r.weighted_vote_score,

    r.author_personaname,
    r.author_avatar,
    r.author_playtime_at_review_minutes,
    r.created_at

FROM ranked AS k
INNER JOIN windows AS w
    USING (window_name)
INNER JOIN winners AS r
    USING (recommendation_id, app_id)
