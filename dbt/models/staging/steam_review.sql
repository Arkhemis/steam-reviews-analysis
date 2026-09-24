-- Dernière version de chaque review : versions moins le registre des versions dépassées.
-- Les consommateurs posent enable_mergejoin = off (cf. dbt_project.yml) : sinon tri des 183 M lignes.
{{ config(materialized='view') }}

SELECT v.*
FROM {{ ref('steam_review_versions') }} AS v
WHERE
    NOT EXISTS (
        SELECT 1
        FROM {{ ref('steam_review_outdated') }} AS o
        WHERE
            o.app_id = v.app_id
            AND o.recommendation_id = v.recommendation_id
            AND o.updated_at = v.updated_at
    )
