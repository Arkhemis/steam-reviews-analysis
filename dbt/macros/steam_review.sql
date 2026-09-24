{#- Parsing du payload JSON, commun à l'append, au premier build et à la compaction. -#}
{% macro steam_review_parse(source_relation) %}
SELECT
    *,

    -- attributs dérivés de review_text, matérialisés ici
    -- afin d'éviter de décompresser encore en aval
    LENGTH(review_text) AS review_text_length,
    COALESCE(review_text ~ '[✅☐]', FALSE) AS is_generic

FROM (

    SELECT
        recommendation_id,
        app_id,

        (payload -> 'author' ->> 'steamid')::bigint AS author_steamid,
        (payload -> 'author' ->> 'personaname') COLLATE "C" AS author_personaname,
        (payload -> 'author' ->> 'profile_url') COLLATE "C" AS author_profile_url,
        (payload -> 'author' ->> 'avatar') COLLATE "C" AS author_avatar,
        (payload -> 'author' ->> 'persona_status') COLLATE "C" AS author_persona_status,
        (payload -> 'author' ->> 'num_games_owned')::int AS author_num_games_owned,
        (payload -> 'author' ->> 'num_reviews')::int AS author_num_reviews,

        -- playtimes Steam sont exprimés en minutes
        (payload -> 'author' ->> 'playtime_forever')::int AS author_playtime_forever_minutes,
        (payload -> 'author' ->> 'playtime_at_review')::int AS author_playtime_at_review_minutes,
        (payload -> 'author' ->> 'playtime_last_two_weeks')::int AS author_playtime_last_two_weeks_minutes,
        TO_TIMESTAMP((payload -> 'author' ->> 'last_played')::bigint) AS author_last_played_at,

        (payload ->> 'review') COLLATE "C" AS review_text,
        payload ->> 'language' AS language,
        (payload ->> 'voted_up')::boolean AS voted_up,
        (payload ->> 'votes_up')::int AS votes_up,

        -- l'API Steam sérialise parfois votes_funny comme un uint32 :
        -- une valeur négative comme -1 devient 4294967295, ce qui dépasse un int4 Postgres
        CASE
            WHEN (payload ->> 'votes_funny')::bigint > 2147483647
                THEN (payload ->> 'votes_funny')::bigint - 4294967296
            ELSE (payload ->> 'votes_funny')::bigint
        END::int AS votes_funny,
        (payload ->> 'weighted_vote_score')::numeric AS weighted_vote_score,
        (payload ->> 'comment_count')::int AS comment_count,
        (payload ->> 'steam_purchase')::boolean AS steam_purchase,
        (payload ->> 'received_for_free')::boolean AS received_for_free,
        (payload ->> 'written_during_early_access')::boolean AS written_during_early_access,
        (payload ->> 'primarily_steam_deck')::boolean AS primarily_steam_deck,
        (payload ->> 'refunded')::boolean AS refunded,

        TO_TIMESTAMP((payload ->> 'app_release_date')::double precision) AS app_release_date,
        payload -> 'reactions' AS reactions,

        TO_TIMESTAMP(timestamp_created) AS created_at,
        TO_TIMESTAMP(timestamp_updated) AS updated_at,
        loaded_at

    FROM {{ source_relation }}

) AS parsed
{% endmacro %}


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

)

{{ steam_review_parse('source_versions') }}
{% endmacro %}


{#- Littéral `max(loaded_at) − recouvrement` : une sous-requête empêcherait Citus
    de sauter les chunk groups de raw. Le premier max se limite aux 30 derniers jours. -#}
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


{#- Watermark du registre : sa dernière nuit réussie (max outdated_at), pas versions,
    qui a déjà rattrapé un éventuel retard. Registre vide (compaction) : repli sur versions. -#}
{% macro steam_review_outdated_watermark(overlap_days) %}
    {%- if not execute -%}
        {{ return("'1970-01-01'::timestamptz") }}
    {%- endif -%}
    {%- set query = "SELECT MAX(outdated_at) - INTERVAL '" ~ overlap_days ~ " days' FROM " ~ this -%}
    {%- set watermark = run_query(query).columns[0].values()[0] -%}
    {%- if watermark is none -%}
        {{ return(steam_review_watermark(ref('steam_review_versions'), overlap_days)) }}
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
    {%- set versions = ref('steam_review_versions') -%}
    {%- set outdated = ref('steam_review_outdated') -%}
    {%- set columns = adapter.get_columns_in_relation(versions) | map(attribute='quoted') | join(', ') -%}

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
        'language', 'voted_up', 'review_text_length', 'is_generic',
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
