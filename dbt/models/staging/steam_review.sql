-- Dernière version de chaque review. ReplacingMergeTree(review_version) ne
-- garde, à la fusion, que la version la plus récente, puis la dernière capture.
-- full_refresh=false : reconstruire doublerait le disque le temps du build.
-- final = 0 : la déduplication de raw est inutile, celle de cette table suffit.
-- max_memory_usage = 0 : le compteur de la requête dérive (3,5 Go comptés pour
-- 300 Mo réels sur 10 % de raw) ; max_server_memory_usage reste le garde-fou.
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

-- Les lignes de raw chargées depuis le dernier passage, moins 2 jours de marge.
-- Les versions relues reviennent avec la même review_version et fusionnent.
{{ steam_review_parse(
    "(SELECT * FROM " ~ source('raw', 'steam_reviews')
    ~ " WHERE loaded_at > (SELECT max(loaded_at) FROM " ~ this ~ ") - INTERVAL 2 DAY)"
) }}

{% else %}

    {{ steam_review_parse(source('raw', 'steam_reviews')) }}

{% endif %}
