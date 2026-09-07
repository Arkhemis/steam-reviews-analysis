/*
    Contrôle négatif : deux moitiés aléatoires d'un même jeu, traitées comme
    deux corpus. Elles parlent du même jeu, donc terms_retained doit valoir 0.
    Sinon la statistique fabrique du signal à partir de bruit.

    Pas un test dbt : il exige sa propre tokenisation. À lancer à la main à
    chaque révision de min_z_score, fdr_q ou min_lexeme_occurrences.
*/

WITH candidate AS (

    SELECT app_id
    FROM {{ ref('review_lexeme_count') }}
    GROUP BY app_id
    ORDER BY SUM(occurrences) DESC
    LIMIT {{ var('negative_control_games', 20) }}

),

eligible AS (

    SELECT
        r.app_id,
        r.review_text,
        ROW_NUMBER() OVER (
            PARTITION BY r.app_id ORDER BY MD5(r.recommendation_id::text)
        ) AS rank_in_game
    FROM {{ ref('steam_review') }} AS r
    INNER JOIN candidate AS c
        ON c.app_id = r.app_id
    WHERE
        r.language = '{{ var("terms_language", "english") }}'
        AND r.author_playtime_at_review_minutes > 120
        AND r.review_text_length > {{ var('min_review_length', 20) }}
        AND NOT r.is_generic

),

halved AS (

    -- L'ordre étant celui d'un hachage, la parité du rang est un tirage
    -- à pile ou face à moitiés égales.
    SELECT
        app_id,
        review_text,
        MOD(rank_in_game, 2) = 0 AS half_b
    FROM eligible
    WHERE rank_in_game <= 2 * {{ var('max_reviews_per_cell', 300) }}

),

lexemes AS (

    SELECT
        h.app_id,
        h.half_b,
        t.lexeme,
        COALESCE(CARDINALITY(t.positions), 1) AS occurrences
    FROM halved AS h,
        LATERAL UNNEST(
            TO_TSVECTOR('{{ var("terms_search_config", "english") }}', h.review_text)
        ) AS t (lexeme, positions, weights)
    WHERE
        LENGTH(t.lexeme) BETWEEN 3 AND 40
        AND t.lexeme ~ '^[[:alpha:]]'

),

half_term AS (

    SELECT
        app_id,
        half_b,
        lexeme,
        SUM(occurrences) AS occurrences,
        COUNT(*) AS reviews
    FROM lexemes
    GROUP BY app_id, half_b, lexeme
    HAVING
        SUM(occurrences) >= {{ var('min_lexeme_occurrences', 3) }}
        AND COUNT(*) >= {{ var('min_reviews_per_lexeme', 3) }}

),

game_term AS (

    SELECT
        app_id,
        lexeme,
        SUM(occurrences) AS occurrences
    FROM half_term
    GROUP BY app_id, lexeme

),

game_size AS (

    SELECT
        app_id,
        SUM(occurrences) AS tokens
    FROM game_term
    GROUP BY app_id

),

half_size AS (

    SELECT
        app_id,
        half_b,
        SUM(occurrences) AS tokens
    FROM half_term
    GROUP BY app_id, half_b

),

confronted AS (

    SELECT
        h.app_id,
        h.half_b,
        h.lexeme,
        h.occurrences::double precision AS y_half,
        (g.occurrences - h.occurrences)::double precision AS y_other,
        hs.tokens::double precision AS n_half,
        (gs.tokens - hs.tokens)::double precision AS n_other,
        g.occurrences::double precision AS alpha_term,
        gs.tokens::double precision AS alpha_total
    FROM half_term AS h
    INNER JOIN game_term AS g
        ON
            g.app_id = h.app_id
            AND g.lexeme = h.lexeme
    INNER JOIN half_size AS hs
        ON
            hs.app_id = h.app_id
            AND hs.half_b = h.half_b
    INNER JOIN game_size AS gs
        ON gs.app_id = h.app_id

),

log_odds AS (

    SELECT
        *,
        LN(
            (y_half + alpha_term) / (n_half + alpha_total - y_half - alpha_term)
        ) - LN(
            (y_other + alpha_term) / (n_other + alpha_total - y_other - alpha_term)
        ) AS delta,
        SQRT(1.0 / (y_half + alpha_term) + 1.0 / (y_other + alpha_term)) AS delta_stderr
    FROM confronted

),

scored AS (

    SELECT
        *,
        delta / delta_stderr AS z_score
    FROM log_odds

),

with_p AS (

    SELECT
        *,
        {{ normal_two_sided_p('z_score') }} AS p_value
    FROM scored

),

ranked AS (

    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY app_id, half_b ORDER BY p_value ASC, lexeme ASC
        ) AS p_rank,
        COUNT(*) OVER (PARTITION BY app_id, half_b) AS tested
    FROM with_p

),

controlled AS (

    SELECT
        *,
        MAX(p_rank) FILTER (
            WHERE p_value <= p_rank * {{ var('fdr_q', 0.05) }} / tested
        ) OVER (PARTITION BY app_id, half_b) AS bh_cutoff
    FROM ranked

)

SELECT
    app_id,
    MAX(tested) AS terms_tested,
    COUNT(*) FILTER (
        WHERE
            z_score >= {{ var('min_z_score', 1.96) }}
            AND p_rank <= bh_cutoff
    ) AS terms_retained
FROM controlled
GROUP BY app_id
ORDER BY terms_retained DESC, app_id ASC
