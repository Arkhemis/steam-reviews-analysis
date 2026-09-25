-- Toutes les versions de chaque review, en append : le columnar interdit UPDATE et DELETE.
-- full_refresh=false : un full refresh passe par compact_steam_review, sans pic disque.
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    on_schema_change='append_new_columns',
    full_refresh=false,
    pre_hook="SET enable_mergejoin = off",
    meta={'analyze_columns': steam_review_analyze_columns()},
) }}

{% if is_incremental() %}

    -- Nuit normale : on ajoute seulement les versions arrivées depuis le dernier chargement.

    -- Étape 1 : les lignes de raw chargées depuis le dernier chargement (moins 2 jours de marge).
    -- Une même version peut avoir été capturée plusieurs fois : on n'en garde qu'une, la plus récente.
    WITH delta AS (

        SELECT DISTINCT ON (app_id, recommendation_id, timestamp_updated) *
        FROM {{ source('raw', 'steam_reviews') }}
        -- devient une date en dur, ex. '2026-09-22 23:10' = dernier loaded_at de la table - 2 jours
        WHERE loaded_at > {{ steam_review_watermark(this, 2) }}
        ORDER BY app_id ASC, recommendation_id ASC, timestamp_updated ASC, loaded_at DESC

    ),

    -- Étape 2 : la marge de 2 jours relit des versions déjà dans la table : on les écarte.
    new_versions AS (

        SELECT d.*
        FROM delta AS d
        WHERE
            NOT EXISTS (
                SELECT 1
                FROM {{ this }} AS v
                WHERE
                    v.app_id = d.app_id
                    AND v.recommendation_id = d.recommendation_id
                    AND v.updated_at = TO_TIMESTAMP(d.timestamp_updated)
            )

    ),

    -- Étape 3 : on transforme le JSON brut de Steam en colonnes.
    {{ steam_review_parse('new_versions') }}

{% else %}

    -- Premier build : la table n'existe pas encore, on la remplit
    -- avec la dernière version de chaque review, depuis tout raw.
    {{ steam_review_latest_versions() }}

{% endif %}
