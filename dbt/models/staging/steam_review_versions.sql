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

    WITH delta AS (

        SELECT DISTINCT ON (app_id, recommendation_id, timestamp_updated) *
        FROM {{ source('raw', 'steam_reviews') }}
        WHERE loaded_at > {{ steam_review_watermark(this, 2) }}
        ORDER BY app_id ASC, recommendation_id ASC, timestamp_updated ASC, loaded_at DESC

    ),

    -- Le recouvrement de 2 jours relit des versions déjà présentes : on les écarte.
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

    )

    {{ steam_review_parse('new_versions') }}

{% else %}

    {{ steam_review_latest_versions() }}

{% endif %}
