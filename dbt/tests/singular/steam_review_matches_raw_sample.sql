-- Chaque dimanche : sur 20 jeux tirés au sort, la staging garde exactement la
-- dernière version de chaque review de raw. Recalcul direct depuis raw.
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
        ORDER BY lower(hex(MD5(concat(toString(app_id), '{{ run_started_at.date() }}'))))
        LIMIT 20
    {% endset %}
    {% set app_ids = run_query(sample_query).columns[0].values() | join(', ') %}

    WITH expected AS (

        SELECT
            app_id,
            recommendation_id,
            toDateTime(max(timestamp_updated), 'UTC') AS updated_at
        FROM {{ source('raw', 'steam_reviews') }}
        WHERE app_id IN ({{ app_ids or 'NULL' }})
        GROUP BY app_id, recommendation_id

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
        'absente de la staging' AS issue,
        *
    FROM missing
    UNION ALL
    SELECT
        'en trop dans la staging' AS issue,
        *
    FROM unexpected

{% else %}

    SELECT 1 WHERE FALSE

{% endif %}
