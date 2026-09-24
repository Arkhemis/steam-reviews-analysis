-- Chaque dimanche : sur 20 jeux tirés au sort, la vue garde exactement la dernière
-- version de chaque review de raw. Recalcul direct, indépendant du registre.
-- depends_on: {{ ref('steam_review') }}, {{ source('raw', 'steam_reviews') }}, {{ source('raw', 'steam_review_counts') }}
{{ config(
    tags=['weekly'],
    meta={'dagster': {'ref': {'name': 'steam_review'}}},
) }}

{% if is_weekly_test_run() and execute %}

    {% set sample_query %}
        SELECT app_id
        FROM {{ source('raw', 'steam_review_counts') }}
        WHERE total_reviews > 0
        ORDER BY MD5(app_id::text || '{{ run_started_at.date() }}')
        LIMIT 20
    {% endset %}
    {% set app_ids = run_query(sample_query).columns[0].values() | join(', ') %}

    WITH expected AS (

        SELECT DISTINCT ON (app_id, recommendation_id)
            app_id,
            recommendation_id,
            TO_TIMESTAMP(timestamp_updated) AS updated_at
        FROM {{ source('raw', 'steam_reviews') }}
        WHERE app_id IN ({{ app_ids or 'NULL' }})
        ORDER BY app_id, recommendation_id, timestamp_updated DESC

    ),

    actual AS (

        SELECT
            app_id,
            recommendation_id,
            updated_at
        FROM {{ ref('steam_review') }}
        WHERE app_id IN ({{ app_ids or 'NULL' }})

    ),

    missing AS (

        SELECT * FROM expected
        EXCEPT ALL
        SELECT * FROM actual

    ),

    unexpected AS (

        SELECT * FROM actual
        EXCEPT ALL
        SELECT * FROM expected

    )

    SELECT
        'absente de la vue' AS issue,
        *
    FROM missing
    UNION ALL
    SELECT
        'en trop dans la vue' AS issue,
        *
    FROM unexpected

{% else %}

    SELECT 1 WHERE FALSE

{% endif %}
