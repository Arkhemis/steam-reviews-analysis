{{
    config(
        indexes=[
            {'columns': ['review_date'], 'type': 'btree'},
            {'columns': ['app_id'], 'type': 'btree'},
        ]
    )
}}

-- review_date : les fenêtres glissantes du site (tendances 30j vs 30j
-- précédents) filtrent sur cette colonne et calculent MAX(review_date) ;
-- sans index chaque appel faisait trois seq scans de la table entière.
-- app_id : lecture de la courbe d'un seul jeu sur sa fiche.

SELECT
    app_id,
    DATE(created_at) AS review_date,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN voted_up THEN 1 ELSE 0 END) AS total_positive,
    SUM(CASE WHEN NOT voted_up THEN 1 ELSE 0 END) AS total_negative,
    ROUND(SUM(CASE WHEN voted_up THEN 1 ELSE 0 END)::numeric / COUNT(*), 4) AS pct_positive
FROM {{ ref('steam_review') }}
GROUP BY 1, 2
