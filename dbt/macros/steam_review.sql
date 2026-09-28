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
