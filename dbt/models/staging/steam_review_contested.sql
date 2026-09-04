-- Les recommendation_id présents en plusieurs versions : 0,6 % des lignes, mais
-- les seules à devoir être triées. Modèle à part et non CTE de steam_review :
-- partagé entre deux branches d'un UNION ALL, un CTE fige le backend (cf. PR).

SELECT recommendation_id

FROM {{ source('raw', 'steam_reviews') }}

GROUP BY recommendation_id

HAVING COUNT(*) > 1
