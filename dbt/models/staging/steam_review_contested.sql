-- Les couples (recommendation_id, app_id) chargés en plusieurs fois : les seules
-- lignes à devoir être triées. Modèle à part et non CTE de steam_review :
-- partagé entre deux branches d'un UNION ALL, un CTE fige le backend (cf. PR).

SELECT
    recommendation_id,
    app_id

FROM {{ source('raw', 'steam_reviews') }}

GROUP BY recommendation_id, app_id

HAVING COUNT(*) > 1
