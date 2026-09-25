{#- Dernière version de chaque review, depuis tout raw : l'état après compaction. -#}
{% macro steam_review_latest_versions() %}
WITH contested AS (

    SELECT
        recommendation_id,
        app_id
    FROM {{ source('raw', 'steam_reviews') }}
    GROUP BY recommendation_id, app_id
    HAVING COUNT(*) > 1

),

source_versions AS (

    SELECT s.*
    FROM {{ source('raw', 'steam_reviews') }} AS s
    WHERE
        NOT EXISTS (
            SELECT 1
            FROM contested AS c
            WHERE
                c.recommendation_id = s.recommendation_id
                AND c.app_id = s.app_id
        )

    UNION ALL

    (
        SELECT DISTINCT ON (s.recommendation_id, s.app_id) s.*
        FROM {{ source('raw', 'steam_reviews') }} AS s
        INNER JOIN contested
            USING (recommendation_id, app_id)
        ORDER BY
            s.recommendation_id ASC,
            s.app_id ASC,
            s.timestamp_updated DESC,
            s.loaded_at DESC
    )

),

{{ steam_review_parse('source_versions') }}
{% endmacro %}


{#- Renvoie la date à partir de laquelle relire raw : dernier chargement moins quelques jours de marge.
    La date est calculée avant la requête et collée en dur dedans. -#}
{% macro steam_review_watermark(relation, overlap_days) %}
    {%- if not execute -%}
        {{ return("'1970-01-01'::timestamptz") }}
    {%- endif -%}
    {%- set recent = (run_started_at - modules.datetime.timedelta(days=30)).isoformat() -%}
    {%- set query -%}
        SELECT COALESCE(
            (SELECT MAX(loaded_at) FROM {{ relation }} WHERE loaded_at > '{{ recent }}'::timestamptz),
            (SELECT MAX(loaded_at) FROM {{ relation }})
        ) - INTERVAL '{{ overlap_days }} days'
    {%- endset -%}
    {%- set watermark = run_query(query).columns[0].values()[0] -%}
    {%- if watermark is none -%}
        {{ exceptions.raise_compiler_error(
            relation ~ " est vide : compaction interrompue ? Relancer `dbt run-operation compact_steam_review`."
        ) }}
    {%- endif -%}
    {{ return("'" ~ watermark.isoformat() ~ "'::timestamptz") }}
{% endmacro %}


{#- Premier jour du mois (ou var) : le registre est recalculé depuis versions pour se corriger. -#}
{% macro steam_review_outdated_full_rebuild() %}
    {{ return(not is_incremental() or var('rebuild_steam_review_outdated', run_started_at.day == 1)) }}
{% endmacro %}


{#- Compaction en place : le TRUNCATE est commité à part pour libérer le disque 
    avant l'INSERT (pas de pic). Lancée par Dagster, voir orchestration/dbt/compaction.py. -#}
{% macro compact_steam_review() %}
    {%- set versions = ref('steam_review_versions').incorporate(type='table') -%}
    {%- set outdated = ref('steam_review_outdated') -%}
    {#- Colonnes de steam_review_parse, pas de la table : une colonne ajoutée est créée
        puis remplie par la réinsertion, une colonne retirée reste à NULL. -#}
    {%- set probe = make_temp_relation(versions) -%}
    {%- set empty_raw = "(SELECT * FROM " ~ source('raw', 'steam_reviews') ~ " LIMIT 0) AS empty_raw" -%}
    {% do run_query(get_create_table_as_sql(True, probe, "WITH " ~ steam_review_parse(empty_raw))) %}
    {% do process_schema_changes('append_new_columns', probe, versions) %}
    {% do adapter.commit() %}
    {%- set columns = adapter.get_columns_in_relation(probe) | map(attribute='quoted') | join(', ') -%}

    {% do log("Compaction : TRUNCATE de " ~ versions ~ " et " ~ outdated, info=true) %}
    {% do _commit_statement("TRUNCATE " ~ versions ~ ", " ~ outdated) %}

    {% do log("Compaction : réinsertion de la dernière version de chaque review", info=true) %}
    {% do _commit_statement(
        "SET max_parallel_workers_per_gather = 0; SET work_mem = '256MB'; SET enable_mergejoin = off;"
        ~ " INSERT INTO " ~ versions ~ " (" ~ columns ~ ") SELECT " ~ columns
        ~ " FROM (" ~ steam_review_latest_versions() ~ ") AS latest"
    ) %}

    {% do _commit_statement(steam_review_analyze(versions, steam_review_analyze_columns()) ~ "; ANALYZE " ~ outdated) %}
    {% do log("Compaction terminée", info=true) %}
{% endmacro %}


{% macro _commit_statement(sql) %}
    {% call statement('compact_steam_review', auto_begin=True) %}{{ sql }}{% endcall %}
    {% do adapter.commit() %}
{% endmacro %}


{#- Columnar échappe à l'autovacuum : ANALYZE explicite, limité aux colonnes utiles
    (lire review_text pour l'échantillon coûte l'essentiel du temps). -#}
{% macro steam_review_analyze(relation, columns=none) %}
    {%- if columns -%}
        ANALYZE {{ relation }} ({{ columns | join(', ') }})
    {%- else -%}
        ANALYZE {{ relation }}
    {%- endif -%}
{% endmacro %}


{#- Colonnes filtrées ou jointes en aval : les seules dont le planner a besoin. -#}
{% macro steam_review_analyze_columns() %}
    {{ return([
        'recommendation_id', 'app_id', 'updated_at', 'created_at', 'loaded_at',
        'language', 'voted_up', 'review_text_length', 'is_generic', 'has_profanity',
    ]) }}
{% endmacro %}


{#- Post-hook de staging : rien sur une vue, colonnes de meta.analyze_columns sinon. -#}
{% macro analyze_model() %}
    {%- if model.config.materialized != 'view' -%}
        {{ steam_review_analyze(this, model.config.meta.get('analyze_columns')) }}
    {%- endif -%}
{% endmacro %}


{#- Le dimanche (UTC) ou avec --vars '{full_tests: true}' : les tests lourds tournent. -#}
{% macro is_weekly_test_run() %}
    {{ return(var('full_tests', false) or run_started_at.isoweekday() == 7) }}
{% endmacro %}


{% test weekly_unique_combination_of_columns(model, combination_of_columns) %}
    {%- if is_weekly_test_run() -%}
        {{ dbt_utils.test_unique_combination_of_columns(model, combination_of_columns) }}
    {%- else -%}
        SELECT 1 WHERE FALSE
    {%- endif -%}
{% endtest %}
