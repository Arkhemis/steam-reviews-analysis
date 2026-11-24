{{ config(order_by='igdb_id') }}

-- Plusieurs concepts PS Store par jeu (concepts PS4 et PS5 distincts, remasters…) : moyenne pondérée par le nombre de notes.
SELECT
    i.igdb_id AS igdb_id,
    round(sum(r.average_rating * r.rating_count) / sum(r.rating_count), 2) AS playstation_average_rating,
    sum(r.rating_count) AS playstation_rating_count,
    arraySort(groupUniqArrayArray(r.platforms)) AS playstation_platforms,
    argMax(concept_id, r.rating_count) AS playstation_concept_id

FROM {{ ref('igdb_game') }} AS i
ARRAY JOIN i.playstation_concept_ids AS concept_id
INNER JOIN {{ source('raw', 'playstation_store_ratings') }} AS r
    USING (concept_id)
GROUP BY i.igdb_id
