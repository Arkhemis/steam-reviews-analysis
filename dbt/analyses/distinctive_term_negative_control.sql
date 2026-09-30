/*
    Contrôle négatif : deux moitiés aléatoires d'un même jeu, traitées comme
    deux corpus. Elles parlent du même jeu, donc terms_retained doit valoir 0.
    Sinon la statistique fabrique du signal à partir de bruit.

    Pas un test dbt : il exige sa propre tokenisation. À lancer à la main à
    chaque révision de min_z_score, fdr_q ou min_lexeme_occurrences, avec
    SETTINGS allow_experimental_nlp_functions = 1 (stem()).
*/

WITH candidate AS (

    SELECT app_id
    FROM {{ ref('review_lexeme_count') }}
    GROUP BY app_id
    ORDER BY sum(occurrences) DESC
    LIMIT {{ var('negative_control_games', 20) }}

),

eligible AS (

    SELECT
        r.recommendation_id AS recommendation_id,
        r.app_id AS app_id,
        r.review_text,
        row_number() OVER (
            PARTITION BY r.app_id ORDER BY lower(hex(MD5(toString(r.recommendation_id))))
        ) AS rank_in_game
    FROM {{ ref('steam_review') }} AS r
    INNER JOIN candidate
        USING (app_id)
    WHERE
        r.language = '{{ var("terms_language", "english") }}'
        AND r.author_playtime_at_review_minutes > 120
        AND r.review_text_length > {{ var('min_review_length', 20) }}
        AND NOT r.is_generic

),

halved AS (

    -- Ordre de hachage : la parité du rang est un pile ou face.
    SELECT
        recommendation_id,
        app_id,
        review_text,
        rank_in_game % 2 = 0 AS half_b
    FROM eligible
    WHERE rank_in_game <= 2 * {{ var('max_reviews_per_cell', 300) }}

),

lexemes AS (

    SELECT
        app_id,
        half_b,
        recommendation_id,
        arrayJoin({{ english_lexemes('review_text') }}) AS lexeme
    FROM halved

),

half_term AS (

    SELECT
        app_id,
        half_b,
        lexeme,
        count() AS occurrences,
        uniqExact(recommendation_id) AS reviews
    FROM lexemes
    GROUP BY app_id, half_b, lexeme
    HAVING
        occurrences >= {{ var('min_lexeme_occurrences', 3) }}
        AND reviews >= {{ var('min_reviews_per_lexeme', 3) }}

),

game_term AS (

    SELECT
        app_id,
        lexeme,
        sum(occurrences) AS occurrences
    FROM half_term
    GROUP BY app_id, lexeme

),

game_size AS (

    SELECT
        app_id,
        sum(occurrences) AS tokens
    FROM game_term
    GROUP BY app_id

),

half_size AS (

    SELECT
        app_id,
        half_b,
        sum(occurrences) AS tokens
    FROM half_term
    GROUP BY app_id, half_b

),

confronted AS (

    SELECT
        h.app_id AS app_id,
        h.half_b AS half_b,
        h.lexeme AS lexeme,
        toFloat64(h.occurrences) AS y_half,
        toFloat64(g.occurrences - h.occurrences) AS y_other,
        toFloat64(hs.tokens) AS n_half,
        toFloat64(gs.tokens - hs.tokens) AS n_other,
        toFloat64(g.occurrences) AS alpha_term,
        toFloat64(gs.tokens) AS alpha_total
    FROM half_term AS h
    INNER JOIN game_term AS g
        USING (app_id, lexeme)
    INNER JOIN half_size AS hs
        USING (app_id, half_b)
    INNER JOIN game_size AS gs
        USING (app_id)

),

log_odds AS (

    SELECT
        *,
        log(
            (y_half + alpha_term) / (n_half + alpha_total - y_half - alpha_term)
        ) - log(
            (y_other + alpha_term) / (n_other + alpha_total - y_other - alpha_term)
        ) AS delta,
        sqrt(1.0 / (y_half + alpha_term) + 1.0 / (y_other + alpha_term)) AS delta_stderr
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
        row_number() OVER (
            PARTITION BY app_id, half_b ORDER BY p_value ASC, lexeme ASC
        ) AS p_rank,
        count() OVER (PARTITION BY app_id, half_b) AS tested
    FROM with_p

),

controlled AS (

    SELECT
        *,
        maxIf(
            p_rank, p_value <= p_rank * {{ var('fdr_q', 0.05) }} / tested
        ) OVER (PARTITION BY app_id, half_b) AS bh_cutoff
    FROM ranked

)

SELECT
    app_id,
    max(tested) AS terms_tested,
    countIf(
        z_score >= {{ var('min_z_score', 1.96) }}
        AND p_rank <= bh_cutoff
    ) AS terms_retained
FROM controlled
GROUP BY app_id
ORDER BY terms_retained DESC, app_id ASC
