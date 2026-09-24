-- Registre des versions dépassées par une plus récente ; la vue steam_review les masque.
-- Heap et petit (< 3 M lignes avant compaction) : le planner le prend comme côté haché.
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    full_refresh=false,
    pre_hook=[
        "SET default_table_access_method = 'heap'; SET enable_mergejoin = off",
        "{% if is_incremental() and steam_review_outdated_full_rebuild() %}TRUNCATE {{ this }}{% endif %}",
    ],
    indexes=[
        {'columns': ['app_id', 'recommendation_id', 'updated_at'], 'unique': True},
    ],
) }}

{% if steam_review_outdated_full_rebuild() %}

    WITH contested AS (

        SELECT
            app_id,
            recommendation_id,
            MAX(updated_at) AS latest_updated_at
        FROM {{ ref('steam_review_versions') }}
        GROUP BY app_id, recommendation_id
        HAVING COUNT(*) > 1

    )

    SELECT
        v.app_id,
        v.recommendation_id,
        v.updated_at,
        NOW() AS outdated_at
    FROM {{ ref('steam_review_versions') }} AS v
    INNER JOIN contested AS c
        ON
            v.app_id = c.app_id
            AND v.recommendation_id = c.recommendation_id
    WHERE v.updated_at < c.latest_updated_at

{% else %}

    -- Reviews touchées depuis la dernière nuit réussie du registre, avec 3 jours de recouvrement.
    WITH touched AS (

        SELECT DISTINCT
            app_id,
            recommendation_id
        FROM {{ source('raw', 'steam_reviews') }}
        WHERE loaded_at > {{ steam_review_outdated_watermark(3) }}

    ),

    candidates AS (

        SELECT
            v.app_id,
            v.recommendation_id,
            v.updated_at,
            MAX(v.updated_at) OVER (
                PARTITION BY v.app_id, v.recommendation_id
            ) AS latest_updated_at
        FROM {{ ref('steam_review_versions') }} AS v
        INNER JOIN touched AS t
            ON
                v.app_id = t.app_id
                AND v.recommendation_id = t.recommendation_id

    )

    SELECT
        c.app_id,
        c.recommendation_id,
        c.updated_at,
        NOW() AS outdated_at
    FROM candidates AS c
    WHERE
        c.updated_at < c.latest_updated_at
        AND NOT EXISTS (
            SELECT 1
            FROM {{ this }} AS o
            WHERE
                o.app_id = c.app_id
                AND o.recommendation_id = c.recommendation_id
                AND o.updated_at = c.updated_at
        )

{% endif %}
