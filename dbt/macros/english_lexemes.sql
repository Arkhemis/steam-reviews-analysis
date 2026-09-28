{#- Lexèmes anglais d'un texte, répétitions comprises : minuscules, découpe sur
    les non-lettres, mots vides de Postgres (english.stop), racine Snowball.
    Remplace to_tsvector('english', …) ; les requêtes qui l'appellent doivent
    activer allow_experimental_nlp_functions. -#}
{% macro english_lexemes(text_column) -%}
    arrayFilter(
        lexeme -> lengthUTF8(lexeme) BETWEEN 3 AND 40 AND match(lexeme, '^[[:alpha:]]'),
        arrayMap(
            word -> stem(word, 'en'),
            arrayFilter(
                word -> NOT has({{ english_stopwords() }}, word),
                splitByNonAlpha(lower(ifNull({{ text_column }}, '')))
            )
        )
    )
{%- endmacro %}


{% macro english_stopwords() -%}
    ['i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your',
    'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her',
    'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs',
    'themselves', 'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those',
    'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
    'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if',
    'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with',
    'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after',
    'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over',
    'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where',
    'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other',
    'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too',
    'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now']
{%- endmacro %}
