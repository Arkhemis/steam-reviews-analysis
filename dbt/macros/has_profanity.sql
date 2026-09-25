{% macro has_profanity(text_column, language_column) -%}
    {%- set swears = {
        "arabic": ["زفت", "خرا", "تبا", "لعنة", "حمار", "كلب"],
        "bulgarian": ["лайно", "курва", "копеле", "шибан", "гъз", "путка"],
        "schinese": ["狗屎", "他妈的", "妈的", "垃圾", "卧槽", "傻逼"],
        "tchinese": ["狗屎", "他媽的", "媽的", "垃圾", "靠北", "白痴"],
        "czech": ["hovno", "kurva", "sračka", "prdel", "debil", "zkurvysyn"],
        "danish": ["lort", "fanden", "pis", "satans", "helvede", "skide", "røv"],
        "dutch": ["kut", "klote", "godverdomme", "verdomme", "tering", "klootzak", "lul"],
        "english": ["shit", "fuck", "crap", "damn", "piss", "dick", "bitch", "ass",
            "fucking", "shitty", "fucked", "bullshit", "asshole", "bastard", "goddamn",
            "dumbass", "motherfucker"],
        "finnish": ["paska", "vittu", "perkele", "saatana", "helvetti", "kusipää",
            "jumalauta"],
        "french": ["merde", "putain", "connard", "bordel", "salope", "enculé", "chiant",
            "con", "pute", "chier"],
        "german": ["Scheiße", "Mist", "Kacke", "Arschloch", "verdammt", "Scheiß",
            "Wichser", "Hurensohn", "Fick"],
        "greek": ["σκατά", "γαμώτο", "μαλάκα", "γαμημένο", "πουτάνα"],
        "hungarian": ["szar", "kurva", "bazmeg", "picsa", "fasz", "geci"],
        "italian": ["merda", "cazzo", "stronzo", "vaffanculo", "minchia", "coglione",
            "porca"],
        "japanese": ["クソ", "くそ", "ちくしょう", "糞", "ふざけんな", "死ね", "馬鹿"],
        "koreana": ["개똥", "씨발", "병신", "젠장", "개새끼", "좆"],
        "norwegian": ["dritt", "faen", "helvete", "jævla", "satan", "drittsekk", "pikk"],
        "polish": ["gówno", "kurwa", "cholera", "pierdolę", "chuj", "dupa", "jebać",
            "spierdalaj"],
        "portuguese": ["merda", "caralho", "foda", "porra", "cabrão", "puta", "foda-se"],
        "brazilian": ["merda", "porra", "caralho", "foda", "bosta", "puta", "cacete",
            "desgraça"],
        "romanian": ["căcat", "dracu", "rahat", "pula", "nasol", "futu-i"],
        "russian": ["говно", "блять", "сука", "хуй", "пиздец", "дерьмо", "мудак", "хрен"],
        "spanish": ["mierda", "joder", "coño", "cabrón", "puta", "gilipollas", "hostia"],
        "latam": ["mierda", "pendejo", "chingada", "verga", "cabrón", "pinche", "carajo",
            "puta"],
        "swedish": ["skit", "fan", "jävla", "helvete", "jävlar", "satan", "kuk",
            "skitsnack"],
        "thai": ["เหี้ย", "ควาย", "สัส", "แม่ง", "ห่า"],
        "turkish": ["bok", "siktir", "amk", "kahretsin", "lanet", "orospu"],
        "ukrainian": ["лайно", "бля", "сука", "хрін", "дідько", "курва", "гівно"],
        "vietnamese": ["cứt", "đéo", "địt", "đm", "vãi", "chó chết", "đồ ngu"]
    } -%}
    {#- Une review en capitales perd souvent ses accents : « ENCULES » pour « enculé ». -#}
    {%- set latin_variants = ["aàáâãäå", "cç", "eéèêë", "iíìîï", "nñ", "oóòôõö", "uúùûü", "yýÿ"] -%}
    {%- set letter_class = {} -%}
    {%- for variants in latin_variants -%}
        {%- for letter in variants -%}{%- do letter_class.update({letter: "[" ~ variants ~ "]"}) -%}{%- endfor -%}
    {%- endfor -%}
    {%- set glued_languages = ["schinese", "tchinese", "japanese", "koreana", "thai"] -%}
    {%- set crude_patterns = {} -%}
    {%- for language, native in swears.items() -%}
        {%- set glued = language in glued_languages -%}
        {%- set words = (swears["english"] if glued else native + swears["english"]) | unique | list -%}
        {%- set long_words = [] -%}
        {%- set short_words = [] -%}
        {%- for word in words -%}
            {%- set chars = [] -%}
            {%- for char in word | lower -%}{%- do chars.append(letter_class.get(char, char)) -%}{%- endfor -%}
            {%- if word | length > 3 -%}{%- do long_words.append(chars | join) -%}{%- else -%}{%- do short_words.append(chars | join) -%}{%- endif -%}
        {%- endfor -%}
        {%- set parts = ["♥"] -%}
        {%- if glued -%}{%- do parts.append(native | join("|")) -%}{%- endif -%}
        {%- do parts.append("\\m(" ~ long_words | join("|") ~ ")(e?s)?\\M") -%}
        {%- if short_words -%}{%- do parts.append("\\m(" ~ short_words | join("|") ~ ")\\M") -%}{%- endif -%}
        {%- do crude_patterns.update({language: parts | join("|")}) -%}
    {%- endfor -%}
    COALESCE(
        CASE {{ language_column }}
        {%- for language, pattern in crude_patterns.items() %}
            WHEN '{{ language }}' THEN {{ text_column }} ~* '{{ pattern }}'
        {%- endfor %}
            ELSE {{ text_column }} ~* '{{ crude_patterns["english"] }}'
        END,
        FALSE
    )
{%- endmacro %}
