{% macro has_profanity(text_column, language_column) -%}
    {%- set swears = {
        "arabic": ["زفت", "خرا", "تبا", "لعنة", "حمار", "كلب",
            "كس", "طيز", "زب", "زبي", "شرموطة", "قحبة", "منيوك", "عرص", "يلعن", "خرة", "كلخرا",
            "خول", "لوطي", "متخلف", "معاق", "زنجي", "عبيد"],
        "bulgarian": ["лайно", "курва", "копеле", "шибан", "гъз", "путка",
            "еба", "ебати", "мамка ти", "мамка му", "кучка", "задник", "лайна", "шибано", "педераст",
            "педал", "негър", "бавноразвиващ", "даун", "циганин", "мангал"],
        "schinese": ["狗屎", "他妈的", "妈的", "垃圾", "卧槽", "傻逼",
            "屎", "他娘的", "操你", "我操", "操蛋", "草泥马", "尼玛", "你妈", "滚蛋", "去死", "牛逼",
            "装逼", "日了狗", "狗日的", "王八蛋", "混蛋", "贱人",
            "基佬", "死基佬", "娘炮", "黑鬼", "支那", "小日本", "鬼子", "智障", "弱智", "脑残", "残废", "棒子", "阿三", "黑奴"],
        "tchinese": ["狗屎", "他媽的", "媽的", "垃圾", "靠北", "白痴",
            "屎", "幹你娘", "機掰", "雞掰", "靠腰", "操你", "我操", "去死", "北七", "王八蛋", "混蛋",
            "賤人", "三小",
            "娘炮", "死娘炮", "黑鬼", "支那", "小日本", "鬼子", "智障", "弱智", "腦殘", "殘廢", "棒子", "阿三", "甲甲", "黑奴"],
        "czech": ["hovno", "kurva", "sračka", "prdel", "debil", "zkurvysyn",
            "píča", "čurák", "zmrd", "kokot", "hajzl", "sakra", "doprdele", "hovadina", "posraný",
            "srát", "jebat", "kretén", "kurvítko", "hovna",
            "buzerant", "buzna", "teplouš", "cigán", "cikán", "negr", "retard", "mongol", "debilní"],
        "danish": ["lort", "fanden", "pis", "satans", "helvede", "skide", "røv",
            "kraftedeme", "fandeme", "pik", "fisse", "lorte", "kælling", "møg", "røvhul", "pikhoved",
            "luder",
            "bøsse", "bøssekarl", "neger", "perker", "mongol", "spasser", "åndssvag", "evnesvag"],
        "dutch": ["kut", "klote", "godverdomme", "verdomme", "tering", "klootzak", "lul",
            "kanker", "godver", "tyfus", "pleuris", "kolere", "eikel", "hoer", "trut", "kak", "stront",
            "zeik", "kutspel", "klotespel", "kutgame", "teringspel", "kankerspel",
            "flikker", "mongool", "kankermongool", "neger", "nikker", "spast", "debiel",
            "achterlijk", "mietje", "zigeuner"],
        "english": ["shit", "fuck", "crap", "damn", "piss", "dick", "bitch", "ass",
            "fucking", "shitty", "fucked", "bullshit", "asshole", "bastard", "goddamn",
            "dumbass", "motherfucker",
            "fuckin", "fucker", "fck", "wtf", "stfu", "motherfucking", "shite", "shithole",
            "shitshow", "horseshit", "dipshit", "batshit", "apeshit", "crappy", "pissed", "cunt",
            "twat", "wanker", "bollocks", "arse", "arsehole", "prick", "cock", "cocksucker",
            "dickhead", "jackass", "douchebag", "whore", "tits", "dammit", "damnit", "goddamnit",
            "slut", "douche", "hell", "cum", "pussy", "wank", "wanking", "bugger", "blowjob",
            "son of a bitch", "sonofabitch", "jizz", "dildo", "boner", "cumshot", "ballsack",
            "nigger", "nigga", "faggot", "fag", "dyke", "tranny", "shemale", "retard", "retarded",
            "spastic", "spaz", "mongoloid", "spic", "chink", "kike", "wetback", "gook", "coon",
            "beaner", "towelhead", "raghead", "sandnigger", "gypsy", "cripple", "midget"],
        "finnish": ["paska", "vittu", "perkele", "saatana", "helvetti", "kusipää",
            "jumalauta",
            "vitun", "vittua", "paskaa", "paskainen", "perkeleen", "saatanan", "helvetin", "perse",
            "kyrpä", "mulkku", "huora", "hitto", "runkku",
            "hintti", "neekeri", "mongoloidi", "vammainen", "jälkeenjäänyt", "ryssä", "mustalainen"],
        "french": ["merde", "putain", "connard", "bordel", "salope", "enculé", "chiant",
            "con", "pute", "chier",
            "ptn", "fdp", "ntm", "tg", "ta gueule", "enfoiré", "bite", "couille", "nique", "niquer",
            "bâtard", "branleur", "chiotte", "emmerde", "emmerdant", "foutre", "foutu", "merdique",
            "pétasse", "salaud", "connerie", "conne", "cul", "chiasse", "fils de pute",
            "pédé", "pd", "tapette", "tarlouze", "gouine", "travelo", "négro", "nègre", "bougnoule",
            "bicot", "raton", "youpin", "bamboula", "chinetoque", "niakoué", "triso", "trisomique",
            "mongol", "attardé", "gogol", "romano"],
        "german": ["Scheiße", "Mist", "Kacke", "Arschloch", "verdammt", "Scheiß",
            "Wichser", "Hurensohn", "Fick",
            "Scheisse", "Scheiss", "beschissen", "Arsch", "Fotze", "Schlampe", "Hure", "ficken",
            "gefickt", "verfickt", "Pisse", "kacken", "Kackspiel", "Scheißspiel", "Scheissspiel",
            "Mistspiel", "Drecksspiel", "Dreck", "Drecks", "Fresse", "Wixer",
            "Schwuchtel", "Tunte", "Neger", "Kanake", "Kanacke", "Zigeuner", "Spast", "Spasti",
            "Mongo", "behindert", "Krüppel", "Judensau", "Kümmeltürke"],
        "greek": ["σκατά", "γαμώτο", "μαλάκα", "γαμημένο", "πουτάνα",
            "σκατα", "γαμωτο", "μαλακα", "γαμημενο", "πουτανα", "γαμώ", "γαμω", "γαμιέσαι", "σκατό",
            "μαλακία", "μαλακίες", "αρχίδια", "αρχιδια", "κώλος", "γαμημένος", "σκατοπαιχνίδο",
            "πούστης", "πούστη", "πουστη", "γύφτος", "γυφτος", "αράπης", "αραπης", "καθυστερημένος",
            "σπαστικός"],
        "hungarian": ["szar", "kurva", "bazmeg", "picsa", "fasz", "geci",
            "baszd meg", "bazdmeg", "basszus", "kibaszott", "kurvára", "picsába", "szarság", "szopás",
            "anyád", "faszság", "faszom", "szaros",
            "buzi", "buzeráns", "köcsög", "néger", "nigger", "cigó", "retardált", "mongol",
            "nyomorék"],
        "indonesian": ["anjing", "bangsat", "kontol", "memek", "tai", "goblok", "tolol",
            "ngentot", "jancok", "asu", "brengsek", "bajingan", "sialan", "kampret", "taik", "anjir",
            "bencong", "banci", "autis", "idiot", "cacat", "negro"],
        "italian": ["merda", "cazzo", "stronzo", "vaffanculo", "minchia", "coglione",
            "porca",
            "cazzata", "cazzate", "incazzato", "stronzata", "porco dio", "dio cane", "fanculo",
            "troia", "puttana", "figa", "culo", "bastardo", "merdoso", "coglioni", "rompicoglioni",
            "cagata", "minchiata", "porca troia", "porca puttana",
            "frocio", "finocchio", "ricchione", "culattone", "negro", "terrone", "mongoloide",
            "ritardato", "handicappato", "zingaro", "mongolo"],
        "japanese": ["クソ", "くそ", "ちくしょう", "糞", "ふざけんな", "死ね", "馬鹿",
            "うんこ", "ちんこ", "まんこ", "くたばれ", "クズ", "ファック", "ぶっ殺", "畜生", "ボケ",
            "ホモ", "オカマ", "ガイジ", "池沼", "キチガイ", "気違い", "ニガー", "チョン", "土人", "知恵遅れ", "カタワ"],
        "koreana": ["개똥", "씨발", "병신", "젠장", "개새끼", "좆",
            "시발", "씨바", "ㅅㅂ", "ㅆㅂ", "존나", "지랄", "염병", "미친", "새끼", "개같", "엿먹어",
            "닥쳐", "ㅈㄴ", "ㅂㅅ",
            "호모", "똥꼬충", "애자", "짱깨", "쪽바리", "깜둥이", "틀딱", "한남충", "김치녀", "찐따", "급식충", "장애새끼"],
        "norwegian": ["dritt", "faen", "helvete", "jævla", "satan", "drittsekk", "pikk",
            "fy faen", "jævel", "jævlig", "helvetes", "kuk", "fitte", "hore", "drittspill", "føkk",
            "pokker", "fanden", "satans", "rævhøl",
            "soper", "neger", "mongo", "tilbakestående", "svarting", "pakkis", "homse"],
        "polish": ["gówno", "kurwa", "cholera", "pierdolę", "chuj", "dupa", "jebać",
            "spierdalaj",
            "kurwy", "kurwa mać", "pierdolony", "pierdolić", "zajebisty", "zajebać", "jebany",
            "jebana", "jebane", "chujowy", "chujowa", "chujnia", "gówniany", "pizda", "skurwysyn",
            "skurwiel", "pojebany", "wypierdalaj", "szmata", "cipa", "dupek", "kurde",
            "pedał", "ciota", "cwel", "pedzio", "czarnuch", "debil", "kretyn", "upośledzony",
            "mongoł", "cygan"],
        "portuguese": ["merda", "caralho", "foda", "porra", "cabrão", "puta", "foda-se",
            "caralhos", "fodido", "foder", "merdoso", "filho da puta", "piça", "cu", "bosta", "chiça",
            "cona", "cabrões",
            "paneleiro", "maricas", "bicha", "preto de merda", "retardado", "mongol", "cigano"],
        "brazilian": ["merda", "porra", "caralho", "foda", "bosta", "puta", "cacete",
            "desgraça",
            "fdp", "vsf", "pqp", "tnc", "cu", "buceta", "piroca", "foder", "fodido", "foda-se",
            "arrombado", "cuzão", "desgraçado", "filho da puta", "merdinha", "otário", "babaca",
            "caralha",
            "viado", "bicha", "boiola", "sapatão", "crioulo", "retardado", "mongol", "macaco"],
        "romanian": ["căcat", "dracu", "rahat", "pula", "nasol", "futu-i",
            "pizda", "pizdă", "muie", "futut", "fut", "dracului", "nenorocit", "curvă", "pulă",
            "coaie", "sugi", "labagiu", "mă-ta", "morții",
            "poponar", "bulangiu", "țigan", "cioară", "handicapat", "retardat", "bozgor", "jidan"],
        "russian": ["говно", "блять", "сука", "хуй", "пиздец", "дерьмо", "мудак", "хрен",
            "бля", "блядь", "нахуй", "нахер", "похуй", "хуйня", "хуйню", "ебать", "ёбаный", "ебаный",
            "заебал", "заебали", "пиздато", "пизда", "херня", "херню", "говнище", "срань", "жопа",
            "мразь", "уёбок", "уебок", "сучка", "говна", "ебучий",
            "пидор", "пидорас", "пидарас", "педик", "хач", "чурка", "жид", "ниггер", "негр", "даун",
            "дебил", "аутист", "хохол", "москаль", "кацап", "чурбан"],
        "spanish": ["mierda", "joder", "coño", "cabrón", "puta", "gilipollas", "hostia",
            "jodido", "hostias", "cojones", "cojón", "polla", "capullo", "mamón", "hijo de puta",
            "hdp", "me cago", "cagada", "gilipollez", "zorra", "carajo", "coñazo", "puto", "putada",
            "maricón", "marica", "bollera", "tortillera", "negrata", "sudaca", "retrasado",
            "subnormal", "mongólico", "sidoso", "panchito"],
        "latam": ["mierda", "pendejo", "chingada", "verga", "cabrón", "pinche", "carajo",
            "puta",
            "chingar", "chingado", "chingón", "pendejada", "culero", "mamada", "mamadas", "puto",
            "hijo de puta", "hdp", "ctm", "conchetumare", "concha", "weon", "huevón", "boludo",
            "pelotudo", "forro", "orto", "chucha", "cagada", "cojudo", "joder",
            "maricón", "marica", "joto", "puñal", "tortillera", "negrata", "sudaca", "retrasado",
            "mongólico", "indio de mierda"],
        "swedish": ["skit", "fan", "jävla", "helvete", "jävlar", "satan", "kuk",
            "skitsnack",
            "fitta", "jävel", "jävligt", "helvetes", "skitspel", "satans", "hora", "fy fan",
            "knulla", "kukhuvud", "skitdåligt", "skitbra",
            "bög", "bögjävel", "neger", "blatte", "blattejävel", "mongo", "efterbliven", "cpunge",
            "zigenare"],
        "thai": ["เหี้ย", "ควาย", "สัส", "แม่ง", "ห่า",
            "เชี่ย", "เย็ด", "ระยำ", "ไอ้สัตว์", "สันดาน", "ส้นตีน", "หน้าหี", "หี", "ควย",
            "ตุ๊ด", "กะเทย", "ปัญญาอ่อน", "ไอ้มืด", "ไอ้เจ๊ก", "ไอ้ปัญญาอ่อน"],
        "turkish": ["bok", "siktir", "amk", "kahretsin", "lanet", "orospu",
            "amına", "amına koyayım", "aq", "mk", "sikeyim", "sikik", "sik", "yarrak", "yarak", "piç",
            "göt", "götveren", "orospu çocuğu", "boktan", "siktiğimin", "amcık",
            "ibne", "puşt", "gerizekalı", "özürlü", "mongol", "kıro", "yavşak", "şerefsiz", "zenci"],
        "ukrainian": ["лайно", "бля", "сука", "хрін", "дідько", "курва", "гівно",
            "блять", "бляха", "хуй", "хуйня", "пизда", "пиздець", "срака", "дупа", "їбати",
            "йобаний", "сраний", "падлюка", "мудак", "холера",
            "підар", "підор", "педик", "жид", "кацап", "москаль", "чурка", "даун", "дебіл", "негр"],
        "vietnamese": ["cứt", "đéo", "địt", "đm", "vãi", "chó chết", "đồ ngu",
            "đụ", "đĩ", "lồn", "cặc", "buồi", "vl", "vcl", "dm", "đmm", "clgt", "óc chó", "mẹ kiếp",
            "vãi lồn", "đéo gì",
            "bê đê", "pê đê", "thằng mọi", "mọi rợ", "thiểu năng", "tàu khựa", "khựa", "mọi đen"]
    } -%}
    {#- Mots anglais qui ont un sens ordinaire dans une autre langue : pas cherchés dans celle-ci. -#}
    {%- set english_false_friends = {
        "german": ["dick", "ass", "hell"],
        "swedish": ["slut", "prick"],
        "danish": ["slut", "fag"],
        "norwegian": ["hell", "fag"],
        "french": ["douche", "retard"],
        "dutch": ["douche"],
        "romanian": ["cum"]
    } -%}
    {#- Une review en capitales perd souvent ses accents : « ENCULES » pour « enculé ».
        Texte et mots sont ramenés à la lettre de base ; İ l'est avant lowerUTF8,
        qui en ferait « i » + point combinant. -#}
    {%- set latin_variants = ["aàáâãäå", "cç", "eéèêë", "iíìîïı", "nñ", "oóòôõö", "uúùûü", "yýÿ"] -%}
    {%- set fold = {} -%}
    {%- for variants in latin_variants -%}
        {%- for letter in variants[1:] -%}{%- do fold.update({letter: variants[0]}) -%}{%- endfor -%}
    {%- endfor -%}
    {%- set folded_text = "translateUTF8(lowerUTF8(translateUTF8(" ~ text_column ~ ", 'İ', 'i')), '"
        ~ fold.keys() | join ~ "', '" ~ fold.values() | join ~ "')" -%}
    {#- Pas de grande regex : les listes de mots sont deux fois plus rapides. Un mot est une
        suite de lettres, chiffres et _, comme avant ; tokens() colle « … » ou « » »
        au mot, et unicodeWord coupe tout caractère non ASCII. -#}
    {%- set text_words = "extractAll(" ~ folded_text ~ ", '[\\\\p{L}\\\\p{N}_]+')" -%}
    {%- set glued_languages = ["schinese", "tchinese", "japanese", "koreana", "thai"] -%}
    {%- set review_language = "if(" ~ language_column ~ " IN ('" ~ swears.keys() | join("', '")
        ~ "'), " ~ language_column ~ ", 'english')" -%}
    {%- set english_words = [] -%}
    {%- set native_words = [] -%}
    {%- set false_friends = [] -%}
    {%- set phrase_checks = {} -%}
    {%- for language in swears -%}
        {%- set glued = language in glued_languages -%}
        {%- set phrase_filters = [] -%}
        {%- set phrases = [] -%}
        {%- for word in (swears["english"] if glued else swears[language] + swears["english"]) | unique -%}
            {%- set english = word in swears["english"] and (language == "english" or word not in swears[language]) -%}
            {#- Découpé comme le texte. -#}
            {%- set folded = [] -%}
            {%- set parts = [""] -%}
            {%- for char in word | lower -%}
                {%- set char = fold.get(char, char) -%}
                {%- do folded.append(char) -%}
                {%- if char.isalnum() or char == "_" -%}{%- do parts.append(parts.pop() ~ char) -%}
                {%- elif parts[-1] -%}{%- do parts.append("") -%}{%- endif -%}
            {%- endfor -%}
            {%- set base = parts | select | join(" ") -%}
            {#- Le pluriel (e?s)? ne vaut que pour les mots de plus de 3 lettres. -#}
            {%- for form in ([base, base ~ "s", base ~ "es"] if word | length > 3 else [base]) -%}
                {%- if " " in form -%}{%- do phrases.append(" " ~ form ~ " ") -%}
                {%- elif not english -%}{%- do native_words.append((language, form)) -%}
                {%- elif language == "english" -%}{%- do english_words.append(form) -%}{%- endif -%}
            {%- endfor -%}
            {%- if " " in base -%}{%- do phrase_filters.append(folded | join) -%}{%- endif -%}
        {%- endfor -%}
        {%- for word in english_false_friends.get(language, []) -%}
            {%- for form in ([word, word ~ "s", word ~ "es"] if word | length > 3 else [word]) -%}
                {%- do false_friends.append((language, form)) -%}
            {%- endfor -%}
        {%- endfor -%}
        {#- Préfiltre sur le texte, puis frontières de mot sur les seules lignes retenues. -#}
        {%- set checks = [] -%}
        {%- if phrases -%}
            {%- do checks.append("multiSearchAny(" ~ folded_text ~ ", ['" ~ phrase_filters | unique | join("', '")
                ~ "']) AND multiSearchAny(concat(' ', arrayStringConcat(" ~ text_words ~ ", ' '), ' '), ['"
                ~ phrases | unique | join("', '") ~ "'])") -%}
        {%- endif -%}
        {%- if glued -%}{%- do checks.append("multiSearchAny(" ~ text_column ~ ", ['" ~ swears[language] | join("', '") ~ "'])") -%}{%- endif -%}
        {%- if checks -%}{%- do phrase_checks.update({language: checks | join(" OR ")}) -%}{%- endif -%}
    {%- endfor -%}
    {%- set native_tuples = [] -%}
    {%- for language, form in native_words | unique -%}{%- do native_tuples.append("('" ~ language ~ "', '" ~ form ~ "')") -%}{%- endfor -%}
    {%- set false_friend_tuples = [] -%}
    {%- for language, form in false_friends -%}{%- do false_friend_tuples.append("('" ~ language ~ "', '" ~ form ~ "')") -%}{%- endfor -%}
    ifNull(
        bitOr(bitOr(
            arrayExists(
                word -> bitOr(
                    ({{ review_language }}, word) IN ({{ native_tuples | join(", ") }}),
                    bitAnd(
                        word IN ('{{ english_words | unique | join("', '") }}'),
                        ({{ review_language }}, word) NOT IN ({{ false_friend_tuples | join(", ") }})
                    )
                ),
                {{ text_words }}
            ),
            {#- multiIf n'évalue que la branche de la langue ; un CASE les évaluerait toutes. #}
            multiIf(
            {%- for language, check in phrase_checks.items() %}
                {{ review_language }} = '{{ language }}', {{ check }},
            {%- endfor %}
                false
            )
        ), position({{ text_column }}, '♥') > 0),
        false
    )
{%- endmacro %}
