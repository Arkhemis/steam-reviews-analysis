{#
    p-value bilatérale d'un score z. PostgreSQL 16 n'a pas erf() : approximation
    d'Abramowitz & Stegun 26.2.17, à moins de 1,4e-7 de erfc.
#}
{%- macro normal_two_sided_p(z) -%}
    {%- set t = '(1.0 / (1.0 + 0.2316419 * ABS(' ~ z ~ ')))' -%}
    LEAST(
        1.0,
        2.0 * EXP(-POWER({{ z }}, 2) / 2.0) / SQRT(2.0 * PI())
        * (
            (
                (
                    (
                        (1.330274429 * {{ t }} - 1.821255978) * {{ t }}
                        + 1.781477937
                    ) * {{ t }} - 0.356563782
                ) * {{ t }} + 0.319381530
            ) * {{ t }}
        )
    )
{%- endmacro -%}
