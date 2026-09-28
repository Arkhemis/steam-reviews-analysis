{{
    config(
        tags=['nlp'],
        order_by='(app_id, voted_up, rank_in_game)',
    )
}}

WITH cell_term AS (

    SELECT
        app_id,
        voted_up,
        lexeme,
        occurrences,
        reviews
    FROM {{ ref('review_lexeme_count') }}

),

corpus_term AS (

    -- Référence de même polarité : comparer les négatives aux négatives
    -- retire le vocabulaire de la déception en général.
    SELECT
        voted_up,
        lexeme,
        sum(occurrences) AS occurrences
    FROM cell_term
    GROUP BY voted_up, lexeme

),

corpus_size AS (

    SELECT
        voted_up,
        sum(occurrences) AS tokens
    FROM corpus_term
    GROUP BY voted_up

),

cell_size AS (

    SELECT
        app_id,
        voted_up,
        sum(occurrences) AS tokens
    FROM cell_term
    GROUP BY app_id, voted_up

),

confronted AS (

    SELECT
        c.app_id AS app_id,
        c.voted_up AS voted_up,
        c.lexeme AS lexeme,
        c.occurrences AS occurrences,
        c.reviews AS reviews,

        toFloat64(c.occurrences) AS y_game,
        toFloat64(k.occurrences - c.occurrences) AS y_rest,
        toFloat64(cs.tokens) AS n_game,
        toFloat64(ks.tokens - cs.tokens) AS n_rest,

        -- Prior de Dirichlet informatif : la fréquence du terme dans tout le
        -- corpus, ce qui régularise les termes rares.
        toFloat64(k.occurrences) AS alpha_term,
        toFloat64(ks.tokens) AS alpha_total

    FROM cell_term AS c
    INNER JOIN corpus_term AS k
        USING (voted_up, lexeme)
    INNER JOIN cell_size AS cs
        USING (app_id, voted_up)
    INNER JOIN corpus_size AS ks
        USING (voted_up)

),

log_odds AS (

    SELECT
        *,
        log(
            (y_game + alpha_term) / (n_game + alpha_total - y_game - alpha_term)
        ) - log(
            (y_rest + alpha_term) / (n_rest + alpha_total - y_rest - alpha_term)
        ) AS delta,
        sqrt(1.0 / (y_game + alpha_term) + 1.0 / (y_rest + alpha_term)) AS delta_stderr

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
        -- p décroît strictement avec |z| : même classement, en triant sur z.
        row_number() OVER (
            PARTITION BY app_id, voted_up ORDER BY abs(z_score) DESC, lexeme ASC
        ) AS p_rank,
        count() OVER (PARTITION BY app_id, voted_up) AS tested
    FROM with_p

),

controlled AS (

    -- Benjamini-Hochberg : plus grand rang k tel que p(k) <= k*q/m.
    SELECT
        *,
        -- Aucun rang retenu : 0, que p_rank (>= 1) ne franchit jamais.
        maxIf(
            p_rank, p_value <= p_rank * {{ var('fdr_q', 0.05) }} / tested
        ) OVER (PARTITION BY app_id, voted_up) AS bh_cutoff
    FROM ranked

),

retained AS (

    SELECT *
    FROM controlled
    WHERE
        -- Test bilatéral, affichage unilatéral : on ne dessine pas une absence.
        z_score >= {{ var('min_z_score', 1.96) }}
        AND p_rank <= bh_cutoff

),

ordered AS (

    SELECT
        app_id,
        voted_up,
        lexeme,
        occurrences,
        reviews,
        p_value,
        round(delta, 4) AS log_odds_delta,
        round(z_score, 2) AS z_score,
        row_number() OVER (
            PARTITION BY app_id, voted_up ORDER BY z_score DESC, lexeme ASC
        ) AS rank_in_game
    FROM retained

)

SELECT *
FROM ordered
WHERE rank_in_game <= {{ var('top_n_distinctive_terms', 30) }}
