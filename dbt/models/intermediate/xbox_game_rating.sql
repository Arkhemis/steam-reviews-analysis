{{ config(order_by='igdb_id') }}

-- Plusieurs produits Microsoft Store par jeu (éditions, PS4/PS5…) : moyenne pondérée par le nombre de notes.
SELECT
    i.igdb_id AS igdb_id,
    round(sum(r.average_rating * r.rating_count) / sum(r.rating_count), 2) AS xbox_average_rating,
    sum(r.rating_count) AS xbox_rating_count

FROM {{ ref('igdb_game') }} AS i
ARRAY JOIN i.xbox_product_ids AS product_id
INNER JOIN {{ source('raw', 'xbox_store_ratings') }} AS r
    USING (product_id)
GROUP BY i.igdb_id
