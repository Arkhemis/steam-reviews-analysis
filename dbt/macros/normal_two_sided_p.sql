{#- p-value bilatérale d'un score z, sous l'hypothèse normale. -#}
{%- macro normal_two_sided_p(z) -%}
    least(1.0, erfc(abs({{ z }}) / sqrt(2)))
{%- endmacro -%}
