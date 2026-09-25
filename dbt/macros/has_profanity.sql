{% macro has_profanity(text_column, language_column) -%}
    {%- set swears = {
        "arabic": ["زفت", "خرا", "تبا", "لعنة", "حمار", "كلب",
            "كس", "طيز", "زب", "زبي", "شرموطة", "قحبة", "منيوك", "عرص", "يلعن", "خرة", "كلخرا"],
        "bulgarian": ["лайно", "курва", "копеле", "шибан", "гъз", "путка",
            "еба", "ебати", "мамка ти", "мамка му", "кучка", "задник", "лайна", "шибано", "педераст"],
        "schinese": ["狗屎", "他妈的", "妈的", "垃圾", "卧槽", "傻逼",
            "屎", "他娘的", "操你", "我操", "操蛋", "草泥马", "尼玛", "你妈", "滚蛋", "去死", "牛逼",
            "装逼", "日了狗", "狗日的", "王八蛋", "混蛋", "贱人"],
        "tchinese": ["狗屎", "他媽的", "媽的", "垃圾", "靠北", "白痴",
            "屎", "幹你娘", "機掰", "雞掰", "靠腰", "操你", "我操", "去死", "北七", "王八蛋", "混蛋",
            "賤人", "三小"],
        "czech": ["hovno", "kurva", "sračka", "prdel", "debil", "zkurvysyn",
            "píča", "čurák", "zmrd", "kokot", "hajzl", "sakra", "doprdele", "hovadina", "posraný",
            "srát", "jebat", "kretén", "kurvítko", "hovna"],
        "danish": ["lort", "fanden", "pis", "satans", "helvede", "skide", "røv",
            "kraftedeme", "fandeme", "pik", "fisse", "lorte", "kælling", "møg", "røvhul", "pikhoved",
            "luder"],
        "dutch": ["kut", "klote", "godverdomme", "verdomme", "tering", "klootzak", "lul",
            "kanker", "godver", "tyfus", "pleuris", "kolere", "eikel", "hoer", "trut", "kak", "stront",
            "zeik", "kutspel", "klotespel", "kutgame", "teringspel", "kankerspel"],
        "english": ["shit", "fuck", "crap", "damn", "piss", "dick", "bitch", "ass",
            "fucking", "shitty", "fucked", "bullshit", "asshole", "bastard", "goddamn",
            "dumbass", "motherfucker",
            "fuckin", "fucker", "fck", "wtf", "stfu", "motherfucking", "shite", "shithole",
            "shitshow", "horseshit", "dipshit", "batshit", "apeshit", "crappy", "pissed", "cunt",
            "twat", "wanker", "bollocks", "arse", "arsehole", "prick", "cock", "cocksucker",
            "dickhead", "jackass", "douchebag", "whore", "tits", "dammit", "damnit", "goddamnit"],
        "finnish": ["paska", "vittu", "perkele", "saatana", "helvetti", "kusipää",
            "jumalauta",
            "vitun", "vittua", "paskaa", "paskainen", "perkeleen", "saatanan", "helvetin", "perse",
            "kyrpä", "mulkku", "huora", "hitto", "runkku"],
        "french": ["merde", "putain", "connard", "bordel", "salope", "enculé", "chiant",
            "con", "pute", "chier",
            "ptn", "fdp", "ntm", "tg", "ta gueule", "enfoiré", "bite", "couille", "nique", "niquer",
            "bâtard", "branleur", "chiotte", "emmerde", "emmerdant", "foutre", "foutu", "merdique",
            "pétasse", "salaud", "connerie", "conne", "cul", "chiasse", "fils de pute"],
        "german": ["Scheiße", "Mist", "Kacke", "Arschloch", "verdammt", "Scheiß",
            "Wichser", "Hurensohn", "Fick",
            "Scheisse", "Scheiss", "beschissen", "Arsch", "Fotze", "Schlampe", "Hure", "ficken",
            "gefickt", "verfickt", "Pisse", "kacken", "Kackspiel", "Scheißspiel", "Scheissspiel",
            "Mistspiel", "Drecksspiel", "Dreck", "Drecks", "Fresse", "Wixer"],
        "greek": ["σκατά", "γαμώτο", "μαλάκα", "γαμημένο", "πουτάνα",
            "σκατα", "γαμωτο", "μαλακα", "γαμημενο", "πουτανα", "γαμώ", "γαμω", "γαμιέσαι", "σκατό",
            "μαλακία", "μαλακίες", "αρχίδια", "αρχιδια", "κώλος", "γαμημένος", "σκατοπαιχνίδο"],
        "hungarian": ["szar", "kurva", "bazmeg", "picsa", "fasz", "geci",
            "baszd meg", "bazdmeg", "basszus", "kibaszott", "kurvára", "picsába", "szarság", "szopás",
            "anyád", "faszság", "faszom", "szaros"],
        "indonesian": ["anjing", "bangsat", "kontol", "memek", "tai", "goblok", "tolol",
            "ngentot", "jancok", "asu", "brengsek", "bajingan", "sialan", "kampret", "taik", "anjir"],
        "italian": ["merda", "cazzo", "stronzo", "vaffanculo", "minchia", "coglione",
            "porca",
            "cazzata", "cazzate", "incazzato", "stronzata", "porco dio", "dio cane", "fanculo",
            "troia", "puttana", "figa", "culo", "bastardo", "merdoso", "coglioni", "rompicoglioni",
            "cagata", "minchiata", "porca troia", "porca puttana"],
        "japanese": ["クソ", "くそ", "ちくしょう", "糞", "ふざけんな", "死ね", "馬鹿",
            "うんこ", "ちんこ", "まんこ", "くたばれ", "クズ", "ファック", "ぶっ殺", "畜生", "ボケ"],
        "koreana": ["개똥", "씨발", "병신", "젠장", "개새끼", "좆",
            "시발", "씨바", "ㅅㅂ", "ㅆㅂ", "존나", "지랄", "염병", "미친", "새끼", "개같", "엿먹어",
            "닥쳐", "ㅈㄴ", "ㅂㅅ"],
        "norwegian": ["dritt", "faen", "helvete", "jævla", "satan", "drittsekk", "pikk",
            "fy faen", "jævel", "jævlig", "helvetes", "kuk", "fitte", "hore", "drittspill", "føkk",
            "pokker", "fanden", "satans", "rævhøl"],
        "polish": ["gówno", "kurwa", "cholera", "pierdolę", "chuj", "dupa", "jebać",
            "spierdalaj",
            "kurwy", "kurwa mać", "pierdolony", "pierdolić", "zajebisty", "zajebać", "jebany",
            "jebana", "jebane", "chujowy", "chujowa", "chujnia", "gówniany", "pizda", "skurwysyn",
            "skurwiel", "pojebany", "wypierdalaj", "szmata", "cipa", "dupek", "kurde"],
        "portuguese": ["merda", "caralho", "foda", "porra", "cabrão", "puta", "foda-se",
            "caralhos", "fodido", "foder", "merdoso", "filho da puta", "piça", "cu", "bosta", "chiça",
            "cona", "cabrões"],
        "brazilian": ["merda", "porra", "caralho", "foda", "bosta", "puta", "cacete",
            "desgraça",
            "fdp", "vsf", "pqp", "tnc", "cu", "buceta", "piroca", "foder", "fodido", "foda-se",
            "arrombado", "cuzão", "desgraçado", "filho da puta", "merdinha", "otário", "babaca",
            "caralha"],
        "romanian": ["căcat", "dracu", "rahat", "pula", "nasol", "futu-i",
            "pizda", "pizdă", "muie", "futut", "fut", "dracului", "nenorocit", "curvă", "pulă",
            "coaie", "sugi", "labagiu", "mă-ta", "morții"],
        "russian": ["говно", "блять", "сука", "хуй", "пиздец", "дерьмо", "мудак", "хрен",
            "бля", "блядь", "нахуй", "нахер", "похуй", "хуйня", "хуйню", "ебать", "ёбаный", "ебаный",
            "заебал", "заебали", "пиздато", "пизда", "херня", "херню", "говнище", "срань", "жопа",
            "мразь", "уёбок", "уебок", "сучка", "говна", "ебучий"],
        "spanish": ["mierda", "joder", "coño", "cabrón", "puta", "gilipollas", "hostia",
            "jodido", "hostias", "cojones", "cojón", "polla", "capullo", "mamón", "hijo de puta",
            "hdp", "me cago", "cagada", "gilipollez", "zorra", "carajo", "coñazo", "puto", "putada"],
        "latam": ["mierda", "pendejo", "chingada", "verga", "cabrón", "pinche", "carajo",
            "puta",
            "chingar", "chingado", "chingón", "pendejada", "culero", "mamada", "mamadas", "puto",
            "hijo de puta", "hdp", "ctm", "conchetumare", "concha", "weon", "huevón", "boludo",
            "pelotudo", "forro", "orto", "chucha", "cagada", "cojudo", "joder"],
        "swedish": ["skit", "fan", "jävla", "helvete", "jävlar", "satan", "kuk",
            "skitsnack",
            "fitta", "jävel", "jävligt", "helvetes", "skitspel", "satans", "hora", "fy fan",
            "knulla", "kukhuvud", "skitdåligt", "skitbra"],
        "thai": ["เหี้ย", "ควาย", "สัส", "แม่ง", "ห่า",
            "เชี่ย", "เย็ด", "ระยำ", "ไอ้สัตว์", "สันดาน", "ส้นตีน", "หน้าหี", "หี", "ควย"],
        "turkish": ["bok", "siktir", "amk", "kahretsin", "lanet", "orospu",
            "amına", "amına koyayım", "aq", "mk", "sikeyim", "sikik", "sik", "yarrak", "yarak", "piç",
            "göt", "götveren", "orospu çocuğu", "boktan", "siktiğimin", "amcık"],
        "ukrainian": ["лайно", "бля", "сука", "хрін", "дідько", "курва", "гівно",
            "блять", "бляха", "хуй", "хуйня", "пизда", "пиздець", "срака", "дупа", "їбати",
            "йобаний", "сраний", "падлюка", "мудак", "холера"],
        "vietnamese": ["cứt", "đéo", "địt", "đm", "vãi", "chó chết", "đồ ngu",
            "đụ", "đĩ", "lồn", "cặc", "buồi", "vl", "vcl", "dm", "đmm", "clgt", "óc chó", "mẹ kiếp",
            "vãi lồn", "đéo gì"]
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
