-- join_collapse_limit : sans lui le planificateur joint corpus_term et
-- cell_size sur voted_up seul, soit 1,7 milliard de lignes à trier.
{{
    config(
        tags=['nlp'],
        pre_hook="SET work_mem = '512MB'; SET hash_mem_multiplier = 4;"
        " SET enable_mergejoin = off; SET join_collapse_limit = 1",
        indexes=[
            {'columns': ['app_id', 'voted_up', 'rank_in_game'], 'type': 'btree'},
        ]
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
        SUM(occurrences) AS occurrences
    FROM cell_term
    GROUP BY voted_up, lexeme

),

corpus_size AS (

    SELECT
        voted_up,
        SUM(occurrences) AS tokens
    FROM corpus_term
    GROUP BY voted_up

),

cell_size AS (

    SELECT
        app_id,
        voted_up,
        SUM(occurrences) AS tokens
    FROM cell_term
    GROUP BY app_id, voted_up

),

confronted AS (

    SELECT
        c.app_id,
        c.voted_up,
        c.lexeme,
        c.occurrences,
        c.reviews,

        c.occurrences::double precision AS y_game,
        (k.occurrences - c.occurrences)::double precision AS y_rest,
        cs.tokens::double precision AS n_game,
        (ks.tokens - cs.tokens)::double precision AS n_rest,

        -- Prior de Dirichlet informatif : la fréquence du terme dans tout le
        -- corpus, ce qui régularise les termes rares.
        k.occurrences::double precision AS alpha_term,
        ks.tokens::double precision AS alpha_total

    FROM cell_term AS c
    INNER JOIN corpus_term AS k
        ON
            k.voted_up = c.voted_up
            AND k.lexeme = c.lexeme
    INNER JOIN cell_size AS cs
        ON
            cs.app_id = c.app_id
            AND cs.voted_up = c.voted_up
    INNER JOIN corpus_size AS ks
        ON ks.voted_up = c.voted_up

),

log_odds AS (

    SELECT
        *,
        LN(
            (y_game + alpha_term) / (n_game + alpha_total - y_game - alpha_term)
        ) - LN(
            (y_rest + alpha_term) / (n_rest + alpha_total - y_rest - alpha_term)
        ) AS delta,
        SQRT(1.0 / (y_game + alpha_term) + 1.0 / (y_rest + alpha_term)) AS delta_stderr

    FROM confronted

),

scored AS MATERIALIZED (

    -- Matérialiser : sinon la macro p-value réexpanse ce calcul six fois.
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
        -- p décroît strictement avec |z| : même classement, sans porter
        -- le polynôme entier en clé de tri.
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up ORDER BY ABS(z_score) DESC, lexeme ASC
        ) AS p_rank,
        COUNT(*) OVER (PARTITION BY app_id, voted_up) AS tested
    FROM with_p

),

controlled AS (

    -- Benjamini-Hochberg : plus grand rang k tel que p(k) <= k*q/m.
    SELECT
        *,
        MAX(p_rank) FILTER (
            WHERE p_value <= p_rank * {{ var('fdr_q', 0.05) }} / tested
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
        ROUND(delta::numeric, 4) AS log_odds_delta,
        ROUND(z_score::numeric, 2) AS z_score,
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up ORDER BY z_score DESC, lexeme ASC
        ) AS rank_in_game
    FROM retained

)

SELECT *
FROM ordered
WHERE rank_in_game <= {{ var('top_n_distinctive_terms', 30) }}
