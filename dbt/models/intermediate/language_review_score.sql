-- Le site lit ce modèle une fiche de jeu à la fois : trié par app_id.
{{ config(order_by='(app_id, language)') }}

WITH by_language AS (

    SELECT
        app_id,
        ifNull(language, 'unknown') AS language,
        count() AS total_reviews,
        countIf(voted_up) AS total_positive
    FROM {{ ref('steam_review') }}
    GROUP BY 1, 2

)

SELECT
    app_id,
    language,
    total_reviews,
    total_positive,
    round(total_positive / total_reviews, 4) AS pct_positive,
    round(
        total_reviews / sum(total_reviews) OVER (PARTITION BY app_id), 4
    ) AS pct_of_total

FROM by_language
