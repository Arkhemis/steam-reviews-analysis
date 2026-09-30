{{
    config(
        tags=['nlp'],
        order_by='(app_id, voted_up, lexeme)',
        query_settings={'allow_experimental_nlp_functions': 1},
    )
}}

WITH eligible AS (

    SELECT
        recommendation_id,
        app_id,
        voted_up
    FROM {{ ref('steam_review') }}
    WHERE
        language = '{{ var("terms_language", "english") }}'
        AND author_playtime_at_review_minutes > 120
        AND review_text_length > {{ var('min_review_length', 20) }}
        AND NOT is_generic

),

ranked AS (

    -- Sans review_text : il ferait trier une quinzaine de Go.
    SELECT
        recommendation_id,
        app_id,
        voted_up,
        count() OVER (PARTITION BY app_id, voted_up) AS reviews_in_cell,

        -- recommendation_id croît avec le temps : ne retiendrait que les reviews de lancement.
        row_number() OVER (
            PARTITION BY app_id, voted_up
            ORDER BY lower(hex(MD5(toString(recommendation_id))))
        ) AS rank_in_cell

    FROM eligible

),

selected AS (

    SELECT
        recommendation_id,
        app_id,
        voted_up
    FROM ranked
    WHERE
        reviews_in_cell >= {{ var('min_reviews_per_cell', 50) }}
        AND rank_in_cell <= {{ var('max_reviews_per_cell', 300) }}

),

-- Un texte copié-collé dans une même cellule ne compte qu'une fois.
sampled AS (

    SELECT
        s.recommendation_id AS recommendation_id,
        s.app_id AS app_id,
        s.voted_up AS voted_up,
        r.review_text AS review_text
    FROM {{ ref('steam_review') }} AS r
    INNER JOIN selected AS s
        USING (recommendation_id, app_id)
    ORDER BY s.app_id, s.voted_up, MD5(r.review_text), s.recommendation_id
    LIMIT 1 BY s.app_id, s.voted_up, MD5(r.review_text)  -- noqa: PRS

),

lexemes AS (

    SELECT
        app_id,
        voted_up,
        recommendation_id,
        arrayJoin({{ english_lexemes('review_text') }}) AS lexeme
    FROM sampled

),

counted AS (

    SELECT
        app_id,
        voted_up,
        lexeme,
        count() AS occurrences,
        uniqExact(recommendation_id) AS reviews
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
