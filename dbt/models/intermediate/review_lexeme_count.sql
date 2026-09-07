{{
    config(
        pre_hook="SET work_mem = '512MB'; SET hash_mem_multiplier = 4; SET max_parallel_workers_per_gather = 0",
        indexes=[
            {'columns': ['app_id', 'voted_up'], 'type': 'btree'},
            {'columns': ['lexeme'], 'type': 'btree'},
        ]
    )
}}

WITH eligible AS (

    SELECT
        recommendation_id,
        app_id,
        voted_up,
        review_text,

        COUNT(*) OVER (PARTITION BY app_id, voted_up) AS reviews_in_cell,

        -- recommendation_id croît avec le temps : trier dessus ne
        -- retiendrait que les reviews de lancement.
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up
            ORDER BY MD5(recommendation_id::text)
        ) AS rank_in_cell

    FROM {{ ref('steam_review') }}
    WHERE
        -- Deux réglages distincts : Steam dit « koreana » ou « brazilian »
        -- là où PostgreSQL attend un nom de configuration de recherche.
        language = '{{ var("terms_language", "english") }}'
        AND author_playtime_at_review_minutes > 120
        AND review_text_length > {{ var('min_review_length', 20) }}
        AND NOT is_generic

),

sampled AS (

    -- Le plafond par cellule fait passer la tokenisation de 49,6 M de
    -- reviews à moins de 6 M, sans perte utile pour un log-odds.
    SELECT DISTINCT ON (app_id, voted_up, MD5(review_text))
        app_id,
        voted_up,
        review_text
    FROM eligible
    WHERE
        reviews_in_cell >= {{ var('min_reviews_per_cell', 50) }}
        AND rank_in_cell <= {{ var('max_reviews_per_cell', 300) }}
    ORDER BY app_id, voted_up, MD5(review_text), recommendation_id

),

lexemes AS (

    SELECT
        s.app_id,
        s.voted_up,
        t.lexeme,
        COALESCE(CARDINALITY(t.positions), 1) AS occurrences
    FROM sampled AS s,
        LATERAL UNNEST(
            TO_TSVECTOR('{{ var("terms_search_config", "english") }}', s.review_text)
        ) AS t (lexeme, positions, weights)
    WHERE
        LENGTH(t.lexeme) BETWEEN 3 AND 40

        -- Écarte nombres, dates et fragments d'URL, que le stemmer laisse passer.
        AND t.lexeme ~ '^[[:alpha:]]'

),

counted AS (

    SELECT
        app_id,
        voted_up,
        lexeme,
        SUM(occurrences) AS occurrences,
        COUNT(*) AS reviews
    FROM lexemes
    GROUP BY app_id, voted_up, lexeme

)

SELECT
    app_id,
    voted_up,
    lexeme,
    occurrences,
    reviews
FROM counted
WHERE
    occurrences >= {{ var('min_lexeme_occurrences', 3) }}
    AND reviews >= {{ var('min_reviews_per_lexeme', 3) }}
