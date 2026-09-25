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

    -- Reconstruction complète (1er du mois) : on repart de zéro et on relit toutes les versions.

    -- Étape 1 : les reviews qui ont plusieurs versions (les autres n'ont rien de périmé),
    -- avec la date de leur version la plus récente.
    WITH contested AS (

        SELECT
            app_id,
            recommendation_id,
            MAX(updated_at) AS latest_updated_at
        FROM {{ ref('steam_review_versions') }}
        GROUP BY app_id, recommendation_id
        HAVING COUNT(*) > 1

    )

    -- Étape 2 : pour ces reviews, toute version plus ancienne que la dernière est périmée, que l'on garde.
    SELECT
        v.app_id,
        v.recommendation_id,
        v.updated_at,
        NOW() AS detected_at
    FROM {{ ref('steam_review_versions') }} AS v
    INNER JOIN contested AS c
        USING (app_id, recommendation_id)
    WHERE v.updated_at < c.latest_updated_at

{% else %}

    -- Nuit normale : on ne regarde que les reviews rechargées récemment.

    -- Depuis la dernière nuit du registre (max detected_at), 3 jours de recouvrement ;
    -- registre vidé par la compaction : repli sur versions. Littéral, pour Citus.
    {%- set last_night = run_query("SELECT MAX(detected_at) FROM " ~ this).columns[0].values()[0] if execute %}

    -- Étape 1 : les reviews que le loader a rechargées depuis la dernière nuit.
    -- Seules elles peuvent avoir reçu une nouvelle version.
    WITH touched AS (

        SELECT DISTINCT
            app_id,
            recommendation_id
        FROM {{ source('raw', 'steam_reviews') }}
        WHERE loaded_at > {% if last_night -%}
            '{{ last_night.isoformat() }}'::timestamptz - INTERVAL '3 days'
        {%- else -%}
            {{ steam_review_watermark(ref('steam_review_versions'), 3) }}
        {%- endif %}

    ),

    -- Étape 2 : toutes les versions de ces reviews, chacune accompagnée
    -- de la date de la version la plus récente de sa review.
    candidates AS (

        SELECT
            v.app_id,
            v.recommendation_id,
            v.updated_at,
            MAX(v.updated_at) OVER (
                PARTITION BY v.app_id, v.recommendation_id
            ) AS latest_updated_at
        FROM {{ ref('steam_review_versions') }} AS v
        INNER JOIN touched
            USING (app_id, recommendation_id)

    )

    -- Étape 3 : on garde les versions plus anciennes que la dernière (donc périmées),
    -- sauf celles déjà dans le registre (le recouvrement de 3 jours les relit).
    SELECT
        c.app_id,
        c.recommendation_id,
        c.updated_at,
        NOW() AS detected_at
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
