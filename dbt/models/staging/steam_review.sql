-- full_refresh=false : reconstruire doublerait le disque le temps du build.
-- final = 0 : la déduplication de cette table suffit.
-- max_memory_usage = 0 : le compteur de la requête surestime ; max_server_memory_usage reste le garde-fou.
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    engine='ReplacingMergeTree(review_version)',
    order_by='(app_id, recommendation_id)',
    settings={'enable_block_number_column': 1, 'enable_block_offset_column': 1},
    query_settings={'final': 0, 'max_memory_usage': 0},
    on_schema_change='append_new_columns',
    full_refresh=false,
    contract={'enforced': true},
) }}

{% if is_incremental() %}

-- 2 jours de marge : les versions relues fusionnent.
{{ steam_review_parse(
    "(SELECT * FROM " ~ source('raw', 'steam_reviews')
    ~ " WHERE loaded_at > (SELECT max(loaded_at) FROM " ~ this ~ ") - INTERVAL 2 DAY)"
) }}

{% else %}

    {{ steam_review_parse(source('raw', 'steam_reviews')) }}

{% endif %}
