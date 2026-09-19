{{
    config(
        pre_hook="SET work_mem = '1GB'",
        indexes=[
            {'columns': ['window_name', 'category', 'language', 'rank'], 'type': 'btree'},
        ]
    )
}}

-- Mêmes bornes que game_window_score : ancrées sur la dernière date ingérée,
-- jamais sur CURRENT_DATE, pour que la fenêtre ne soit pas vide quand
-- l'ingestion a plusieurs jours de retard.
WITH bounds AS (

    SELECT MAX(review_date) AS latest
    FROM {{ ref('game_review_trend_daily') }}

),

windows AS (

    SELECT
        'week' AS window_name,
        (latest - INTERVAL '6 days')::DATE AS starts_on,
        latest AS ends_on
    FROM bounds

    UNION ALL

    SELECT
        'month' AS window_name,
        (latest - INTERVAL '29 days')::DATE AS starts_on,
        latest AS ends_on
    FROM bounds

),

-- Une seule lecture de steam_review sert les deux fenêtres : la plus large
-- (trente jours) contient l'autre. La table est columnar et sans index : le
-- filtre sur created_at, comparé à une valeur connue dès le début du scan,
-- laisse Citus sauter les chunk groups hors fenêtre, et seules les colonnes
-- citées ici sont décompressées. Le CTE est relu plus bas pour récupérer le
-- texte des lauréats : MATERIALIZED garantit qu'on ne rescanne pas la source.
recent_reviews AS MATERIALIZED (

    SELECT
        recommendation_id,
        app_id,
        language,
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
        created_at >= (SELECT (b.latest - INTERVAL '29 days')::DATE FROM bounds AS b)
        AND review_text_length > {{ var('min_review_length', 20) }}
        AND NOT is_generic
        AND language IS NOT NULL

        -- votes_funny peut être négatif en staging (sérialisation uint32 de
        -- l'API) : la comparaison stricte l'écarte d'office.
        AND (votes_funny > 0 OR votes_up > 0)

),

-- Une ligne par (fenêtre, catégorie, review) éligible. Le texte et l'auteur
-- ne sont pas portés ici : les deux tris qui suivent n'ont besoin que des
-- compteurs, et trimballer review_text dans chaque tri coûterait cher.
candidates AS (

    SELECT
        w.window_name,
        c.category,
        r.language,
        r.app_id,
        r.recommendation_id,
        r.votes_up,

        -- Clé de tri principale propre à chaque catégorie : les votes « drôle »
        -- pour funny, le score pondéré de Steam pour helpful.
        CASE
            WHEN c.category = 'funny' THEN r.votes_funny::NUMERIC
            ELSE r.weighted_vote_score
        END AS primary_score

    FROM recent_reviews AS r
    INNER JOIN windows AS w
        ON DATE(r.created_at) BETWEEN w.starts_on AND w.ends_on
    CROSS JOIN (VALUES ('funny'), ('helpful')) AS c (category)
    WHERE
        (c.category = 'funny' AND r.votes_funny > 0)
        OR (c.category = 'helpful' AND r.votes_up > 0)

),

-- Un jeu très commenté placerait sinon ses cinq meilleures reviews sur le
-- podium : on ne garde que la meilleure de chaque jeu avant de classer.
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
            ROW_NUMBER() OVER (
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
            ROW_NUMBER() OVER (
                PARTITION BY window_name, category, language
                ORDER BY primary_score DESC, votes_up DESC, recommendation_id ASC
            ) AS rank
        FROM best_per_game
    ) AS ranked_games
    WHERE rank <= {{ var('top_n_window_reviews', 5) }}

)

SELECT
    k.window_name,
    k.category,
    k.language,
    k.rank::INT AS rank,
    w.starts_on,
    w.ends_on,

    r.recommendation_id,
    r.app_id,
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
    ON k.window_name = w.window_name
INNER JOIN recent_reviews AS r
    ON
        k.recommendation_id = r.recommendation_id
        AND k.app_id = r.app_id
