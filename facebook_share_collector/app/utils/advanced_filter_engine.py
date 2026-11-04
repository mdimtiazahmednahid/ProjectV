import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from app.models.share_profile import ContestParticipant
from app.utils.text_normalizer import normalize_text

# Any English letter, digit, or Bengali Unicode character (\u0980-\u09FF)
VALID_CONTENT_RE = re.compile(r"[a-zA-Z0-9\u0980-\u09FF]")
WORD_CHAR_CLASS = r"a-zA-Z0-9\u0980-\u09FF"
PUNCT_STRIP_RE = re.compile(r"^[^\w\u0980-\u09FF]+|[^\w\u0980-\u09FF]+$", re.UNICODE)

# DrawSystem Bangla + English gender name token dictionaries
MALE_TOKENS: Set[str] = {
    "md", "mohammad", "muhammad", "mohammed", "ahmed", "ahmad", "islam", "hossain", "hossein",
    "hasan", "hassan", "rahman", "rahim", "karim", "ali", "khan", "chowdhury", "alam", "udin",
    "uddin", "mia", "miah", "sheikh", "sk", "kazi", "syed", "tarek", "tariq", "faruk", "farooq",
    "habib", "kabir", "ashraf", "masud", "mamun", "sohel", "rubel", "rasel", "russell", "sumon",
    "suman", "sujon", "liton", "ripon", "milton", "shanto", "shuvo", "shakib", "sakib", "tamim",
    "mushfiq", "riyad", "mehedi", "mahmud", "mahmudul", "nahid", "fahim", "faisal", "imran",
    "irfan", "kamrul", "khaled", "mahfuz", "manik", "maruf", "mazhar", "mizan", "mizanur",
    "mobarak", "monir", "monirul", "mostafa", "mustafa", "munna", "murad", "nadim", "naim",
    "nasir", "nazmul", "noman", "omar", "osman", "parvez", "polash", "palash", "rabbi", "rafiq",
    "rafiqul", "raihan", "rajib", "rakib", "rakibul", "ramzan", "rana", "rashed", "rashedul",
    "ratan", "raza", "reza", "rezaul", "riad", "rifat", "robin", "rokon", "romel", "rony",
    "ruhul", "saad", "sabbir", "sadiq", "sadman", "sagor", "saif", "saiful", "sajid", "sajjad",
    "salam", "salman", "samad", "samir", "samiul", "sanaullah", "sanowar", "sarwar", "sattar",
    "sayed", "sayem", "selim", "shafiq", "shafiqul", "shah", "shahab", "shahin", "shahid",
    "shahidul", "shajalal", "shahjahan", "shahriar", "shamim", "shamsul", "sharif", "shariful",
    "shawon", "shihab", "shohag", "shohel", "shorif", "shovon", "siddiq", "siraj", "sohan",
    "sojib", "sajib", "solaiman", "sourav", "subrata", "sujan", "sultan", "sunny", "tanjil",
    "tanvir", "tapos", "tauhid", "towhid", "tuhin", "ujjal", "wahid", "yeasin", "yasin",
    "yousuf", "yusuf", "zahid", "zahidul", "zahir", "zakaria", "zakir", "zaman", "zia", "zillur",
    "zubair", "arafat", "arman", "asif", "atik", "atiq", "azad", "aziz", "babul", "badal",
    "bappy", "bashar", "belal", "biplob", "bulbul", "chandan", "dalim", "delwar", "didar",
    "dipu", "dulal", "ebrahim", "ibrahim", "elias", "emon", "enamul", "farhad", "ferdous",
    "forhad", "gias", "golam", "hafiz", "hamid", "hanif", "harun", "hemayet", "himel", "hridoy",
    "humayun", "iqbal", "ismail", "jahangir", "jahid", "jalal", "jamal", "jamil", "jasim",
    "jashim", "javed", "jewel", "jibon", "joy", "joynal", "juel", "kalam", "kamal", "kawser",
    "kawsar", "khairul", "khalil", "khokon", "khorshed", "kibria", "limon", "lokman", "lutfor",
    "mahbub", "mahbubur", "majed", "malek", "mannan", "mansur", "masum", "matin", "meherab",
    "milon", "miraj", "mithu", "mitul", "mofiz", "mohsin", "moin", "moinul", "mokbul", "momen",
    "momin", "monwar", "morshed", "mosharraf", "motaleb", "mozammel", "muhib", "muktar", "mukul",
    "munir", "mursalin", "morsalin", "musa", "mushfiqur", "mustafiz", "mustakim", "nafis",
    "nahian", "najmul", "nasim", "nayem", "nayeem", "nazim", "nizam", "noyon", "nur", "nurul",
    "obaidul", "oli", "pavel", "piash", "pias", "plabon", "pranto", "prince", "proshanto",
    "quader", "kader", "quddus", "rafi", "rahat", "rahul", "raju", "ramim", "ranju", "rashid",
    "ratul", "rayhan", "redwan", "ridoy", "riaz", "riyadh", "rizvi", "roni", "rupok", "sabit",
    "saddam", "sadek", "sadik", "safaet", "shafayet", "saghor", "sahabuddin", "saikat", "saim",
    "sajal", "saju", "sakhawat", "salim", "samrat", "santo", "sanwar", "sarowar", "sazzad",
    "shadat", "shadhin", "shafik", "shahan", "shahed", "shaheen", "shahinur", "shahnewaz",
    "shajal", "shajahan", "shakil", "shamol", "shams", "shamsuddin", "shanta", "shapan",
    "swapan", "sharafat", "shariar", "shashi", "shaukat", "shawkat", "shehab", "shibli",
    "shimul", "razzak", "abdul", "abdullah", "abdur",
    # Bangla male prefixes/names
    "মো", "মোঃ", "মোহাম্মদ", "মুহাম্মদ", "আহমেদ", "ইসলাম", "হোসেন", "হাসান", "রহমান",
    "রহিম", "করিম", "আলী", "খান", "চৌধুরী", "আলম", "উদ্দিন", "মিয়া", "মিয়া", "শেখ",
    "কাজী", "সৈয়দ", "তারেক", "ফারুক", "হাবিব", "কবির", "মাসুদ", "মামুন", "সোহেল",
    "রুবেল", "রাসেল", "সুমন", "সুজন", "লিটন", "রিপন", "শান্ত", "শুভ", "সাকিব", "তামিম",
    "মুশফিক", "রিয়াদ", "মেহেদী", "মাহমুদ", "নাহিদ", "ফাহিম", "ফয়সাল", "ইমরান",
    "কামরুল", "মাহফুজ", "মানিক", "মারুফ", "মিজান", "মনির", "মোস্তফা", "মুন্না", "মুরাদ",
    "নাদিম", "নাইম", "নাসির", "নাজমুল", "নোমান", "ওমর", "পারভেজ", "পলাশ", "রাব্বি",
    "রফিক", "রায়হান", "রাজিব", "রাকিব", "রমজান", "রানা", "রাশেদ", "রতন", "রেজা",
    "রিফাত", "রবিন", "রনি", "সাদ", "সাব্বির", "সাদমান", "সাগর", "সাইফ", "সাইফুল",
    "সাজিদ", "সাজ্জাদ", "সালাম", "সালমান", "সামির", "সারোয়ার", "সাঈদ", "সেলিম",
    "শফিক", "শাহ", "শাহীন", "শহীদ", "শাহরিয়ার", "শামীম", "শরীফ", "শাওন", "শিহাব",
    "সোহাগ", "শোভন", "সোহান", "সজীব", "সৌরভ", "সুলতান", "তানভীর", "তৌহিদ", "তুহিন",
    "উজ্জ্বল", "ইয়াসিন", "ইউসুফ", "জাহিদ", "জাকির", "জামান", "জিয়া", "জুবায়ের",
    "আরাফাত", "আরমান", "আসিফ", "আতিক", "আজাদ", "আজিজ", "বাবুল", "বাপ্পি", "বেলাল",
    "বিপ্লব", "দিপু", "ইব্রাহিম", "ইমন", "এনামুল", "ফরহাদ", "ফেরদৌস", "গোলাম", "হাফিজ",
    "হামিদ", "হানিফ", "হারুন", "হিমেল", "হৃদয়", "হুমায়ুন", "ইকবাল", "ইসমাইল", "জাহাঙ্গীর",
    "জালাল", "জামাল", "জসিম", "জুয়েল", "জীবন", "জয়", "কালাম", "কামাল", "কাউসার",
    "খায়রুল", "খোকন", "লিমন", "লোকমান", "মাহবুব", "মালেক", "মান্নান", "মাসুম", "মিলন",
    "মিরাজ", "মিঠু", "মহসিন", "মঈন", "মোমিন", "মোর্শেদ", "মোশাররফ", "মোজাম্মেল",
    "মুকুল", "মুনির", "মুসা", "মুস্তাফিজ", "নাফিস", "নাসিম", "নাঈম", "নাজিম", "নয়ন",
    "নুর", "নুরুল", "পাভেল", "পিয়াস", "প্লাবন", "প্রান্ত", "কাদের", "রাফি", "রাহাত",
    "রাহুল", "রাজু", "রাশিদ", "রাতুল", "রেদওয়ান", "রিয়াজ", "রিজভী", "রুপক", "সাদ্দাম",
    "সাদেক", "সৈকত", "সজল", "সاجু", "সম্রাট", "স্বপন", "শাকিল", "শ্যামল", "শিমুল",
    "আব্দুল", "আব্দুল্লাহ", "আব্দুর",
}

FEMALE_TOKENS: Set[str] = {
    "mst", "most", "mosammat", "musammat", "begum", "akter", "akhter", "aktar", "khatun",
    "khanam", "parvin", "parveen", "yeasmin", "yasmin", "jesmin", "jahan", "sultana",
    "nahar", "nesa", "nessa", "bibi", "banu", "ara", "faria", "farzana", "fatema", "fatima",
    "halima", "hasina", "helena", "humaira", "ishrat", "israt", "jannat", "jannatul",
    "ferdousi", "kabita", "khadija", "khaleda", "kulsum", "laila", "laizu", "lima", "lipi",
    "liza", "lovely", "lubna", "mahfuza", "mahmuda", "maisha", "maliha", "mariam", "marium",
    "marjana", "masuda", "mehjabin", "mim", "mimi", "mina", "mitu", "moni", "monira",
    "morsheda", "mou", "mousumi", "mukta", "munni", "murshida", "nadia", "nafisa", "nahida",
    "naima", "najma", "nasima", "nasrin", "nazma", "naznin", "neela", "nila", "nilufa",
    "nipa", "usrat", "nusrat", "papiya", "pinky", "poly", "popi", "popy", "priya", "priyanka",
    "puja", "rabeya", "rahela", "rahima", "raka", "rani", "rashida", "ratna", "raziea",
    "razia", "rehana", "rekha", "irene", "reshma", "ria", "ripa", "rita", "ritu", "rokeya",
    "roma", "rowshan", "rozina", "rubi", "rubina", "ruma", "rumana", "rupa", "rupali",
    "sabina", "sabrina", "sadia", "sadiya", "salma", "samia", "samira", "sanjida", "sapna",
    "swapna", "sarmin", "sharmin", "shabana", "shabnam", "shahnaj", "shahnaz", "shahina",
    "shakila", "shamima", "shampa", "shammi", "shanta", "shapla", "sharifa", "shathi",
    "shefali", "sheuli", "shila", "shilpi", "shima", "shirin", "shirina", "shiuly", "shobha",
    "shohagi", "shoma", "shompa", "sonia", "sumaiya", "sumi", "sumona", "suraiya", "surovi",
    "sweeti", "sweety", "tahmina", "tania", "tanha", "tanjina", "tanjila", "tanni", "taslima",
    "tasnim", "tasnima", "tina", "tithi", "trisha", "tumpa", "tuni", "umme", "urmi",
    "zakia", "zarin", "zinat", "zohra", "afroza", "afsana", "afroja", "amen", "amena",
    "anika", "anjuman", "ankhi", "akhi", "arifa", "asha", "asma", "asmani", "ayesha", "aziza",
    "baby", "beauty", "bithi", "bristy", "brishti", "champa", "chandni", "chumki", "dalia",
    "dilara", "dipa", "dipali", "doli", "doly", "eva", "fahima", "fahmida", "farhana", "farida",
    # Bangla female prefixes/names
    "মোসা", "মোসাঃ", "মোসাম্মৎ", "বেগম", "আক্তার", "খাতুন", "খানম", "পারভীন",
    "ইয়াসমিন", "জেসমিন", "জাহান", "সুলতানা", "নাহার", "নেছা", "বিবি", "বানু", "আরা",
    "ফারিয়া", "ফারজানা", "ফাতেমা", "হালিমা", "হাসিনা", "হুমায়রা", "ইশরাত", "ইসরাত",
    "জান্নাত", "জান্নাতুল", "ফেরদৌসী", "কবিতা", "খাদিজা", "খালেদা", "কুলসুম", "লায়লা",
    "লিমা", "লিপি", "লিজা", "লাভলী", "লুবনা", "মাহফুজা", "মাহমুদা", "মাইশা", "মালিহা",
    "মরিয়ম", "মারজানা", "মাসুদা", "মেহজাবিন", "মিম", "মিনা", "মিতু", "মনি", "মনিরা",
    "মৌ", "মৌসুমী", "মুক্তা", "মুন্নি", "নাদিয়া", "নাফিসা", "নাহিদা", "নাইমা", "নাজমা",
    "নাসিমা", "নাসরিন", "নাজনীন", "নীলা", "নিলুফা", "নিপা", "নুসরাত", "পাপিয়া", "পিংকি",
    "পলি", "পপি", "প্রিয়া", "প্রিয়াঙ্কা", "পূজা", "রাবেয়া", "রাহেলা", "রহিমা", "রাণী",
    "রানী", "রাশিদা", "রত্না", "রাজিয়া", "রেহানা", "রেখা", "রেশমা", "রিয়া", "রিপা",
    "রিতা", "রিতু", "রোকেয়া", "রোজিনা", "রুবি", "রুবিনা", "রুমা", "রুমানা", "রুপা",
    "সাবিনা", "সাবরিনা", "সাদিয়া", "সালমা", "সামিয়া", "সামিরা", "সানজিদা", "স্বপ্না",
    "শারমিন", "শাবানা", "শাহনাজ", "শাকিলা", "শামীমা", "শম্পা", "শান্তা", "শাপলা",
    "সাথী", "শেফালী", "শিউলি", "শিলা", "শিল্পী", "সীমা", "শিরিন", "সোনিয়া", "সুমাইয়া",
    "সুমি", "সুমনা", "সুরাইয়া", "তাহমিনা", "তানিয়া", "তানহা", "তানজিনা", "তানজিলা",
    "তাসলিমা", "তাসনিম", "তিথি", "তৃষা", "টুম্পা", "উম্মে", "উর্মি", "জাকিয়া", "জেরিন",
    "আফরোজা", "আফসানা", "আমেনা", "আনিকা", "আঁখি", "আরিফা", "আশা", "আসমা", "আয়েশা",
    "বিথী", "বৃষ্টি", "চম্পা", "ডালিয়া", "দিলারা", "দীপা", "ডলি", "ফাহিমা", "ফাহমিদা",
    "ফারহানা", "ফরিদা",
}


@dataclass
class AdvancedFilterConfig:
    """
    Configuration for Advanced Contest Filtering with Boolean Logic (AND / OR / NOT)
    inspired by FairDraw (DrawSystem) + custom multi-rule evaluation.
    """
    or_keywords: str = ""            # Group 1 (OR): Match ANY of these right answers / keywords
    and_keywords: str = ""           # Group 2 (AND): Must contain ALL of these keywords
    not_keywords: str = ""           # Group 3 (NOT): Wrong answers / excluded spam keywords
    boolean_query: str = ""          # Optional inline boolean query e.g. "(ready OR রেডি) AND NOT fake"
    match_mode: str = "whole_word"   # "whole_word" | "contains" | "exact" | "regex"
    min_comment_length: int = 0      # Minimum comment character length
    min_word_count: int = 0          # Minimum comment word count
    exclude_invalid_emoji: bool = False  # Reject comments that only have emojis/punctuation
    require_mention_or_hashtag: bool = False  # Require @mention or #hashtag
    gender_filter: str = "all"       # "all" | "male" | "female" | "unknown"
    quick_category: str = "all"      # "all" | "qualified" | "correct" | "wrong" | "invalid" | "no_comments" | "duplicates" | "disqualified"
    include_share_text: bool = True  # Check share_contents in addition to comment_texts

    def has_active_keyword_rules(self) -> bool:
        return bool(
            self.or_keywords.strip()
            or self.and_keywords.strip()
            or self.not_keywords.strip()
            or self.boolean_query.strip()
        )

    def has_any_rule_constraints(self) -> bool:
        return bool(
            self.has_active_keyword_rules()
            or self.min_comment_length > 0
            or self.min_word_count > 0
            or self.exclude_invalid_emoji
            or self.require_mention_or_hashtag
            or self.gender_filter not in ("all", "")
        )


@dataclass
class ParticipantEvaluation:
    """
    Stores the computed FairDraw / DrawSystem evaluation state for a single ContestParticipant.
    """
    has_comment: bool = False
    is_invalid_emoji_only: bool = False
    matches_or: bool = True
    matches_and: bool = True
    matches_not_excluded: bool = False  # True if disqualified by NOT / Wrong keyword
    matches_boolean_query: bool = True
    matches_length: bool = True
    matches_mention_hashtag: bool = True
    matches_gender: bool = True
    detected_gender: str = "unknown"    # "male" | "female" | "unknown"
    is_duplicate_name: bool = False
    is_disqualified: bool = False
    is_correct_answer: bool = False
    is_wrong_answer: bool = False
    passes_all_custom_rules: bool = True
    is_qualified_winner: bool = False   # 3/3 actions + passes_all_custom_rules + not disqualified
    reason_badge: str = ""


class AdvancedFilterEngine:
    """
    Evaluates ContestParticipants against DrawSystem's advanced filtering rules:
    - Boolean `OR` (Any right answer), `AND` (All required keywords), `NOT` (Wrong answers / Exclude)
    - Inline Boolean Expression parser (`(apple OR আপেল) AND fresh NOT rotten`)
    - Unicode Bangla + English Whole-Word Boundary matching (`4` != `14`, `ভালো` != `ভালোবাসি`)
    - Exact Match & Regex Match modes
    - Emoji-only / Invalid comment detection (`![a-zA-Z0-9\\u0980-\\u09FF]`)
    - Gender detection (`Male`, `Female`, `Unknown`)
    - Live Category Pill counts & percentages (`All`, `Qualified`, `Correct`, `Wrong`, `Invalid`, `No Comments`, `Duplicates`, `Disqualified`)
    """

    @staticmethod
    def parse_keyword_list(raw: str) -> List[str]:
        if not raw or not raw.strip():
            return []
        # Support comma, newline, or semicolon separated keywords, and also strip inline OR/AND tokens if typed in simple box
        parts = re.split(r"[,;\n]+", raw)
        cleaned = []
        for p in parts:
            t = p.strip()
            if not t:
                continue
            cleaned.append(t)
        return cleaned

    @staticmethod
    def is_valid_meaningful_text(text: str) -> bool:
        """
        Matches DrawSystem's `isInvalid`: returns True only if text has at least one
        English letter, digit, or Bangla Unicode character (\\u0980-\\u09FF).
        Emoji-only or punctuation-only comments return False.
        """
        if not text or not text.strip():
            return False
        return bool(VALID_CONTENT_RE.search(text))

    @staticmethod
    def detect_gender(name: str) -> str:
        """
        Detects 'male', 'female', or 'unknown' from Bangla or English participant display names
        using DrawSystem's token dictionary.
        """
        if not name or not name.strip():
            return "unknown"
        norm = normalize_text(name).lower()
        tokens = [
            PUNCT_STRIP_RE.sub("", tok)
            for tok in re.split(r"[\s._\-,()/]+", norm)
            if tok.strip()
        ]
        for tok in tokens:
            if not tok:
                continue
            if tok in FEMALE_TOKENS:
                return "female"
            if tok in MALE_TOKENS:
                return "male"
        return "unknown"

    @classmethod
    def match_single_keyword(cls, text: str, keyword: str, match_mode: str = "whole_word") -> bool:
        """
        Matches a single keyword against a single comment/share string using the selected mode:
        - "contains": Case-insensitive substring match
        - "whole_word": Unicode-aware word boundary for English + Bangla (`test_regex.php`)
        - "exact": Entire comment (stripped of surrounding punctuation/spaces) equals keyword
        - "regex": Custom regular expression
        """
        if not text or not keyword:
            return False

        kw = keyword.strip()
        if not kw:
            return False

        text_norm = normalize_text(text)
        kw_norm = normalize_text(kw)
        mode = (match_mode or "whole_word").lower().strip()

        if mode == "contains":
            return kw_norm.lower() in text_norm.lower()

        if mode == "exact":
            t_clean = PUNCT_STRIP_RE.sub("", text_norm.strip()).lower()
            k_clean = PUNCT_STRIP_RE.sub("", kw_norm.strip()).lower()
            if not k_clean:
                return text_norm.strip().lower() == kw_norm.strip().lower()
            return t_clean == k_clean

        if mode == "regex":
            try:
                return bool(re.search(kw, text_norm, flags=re.IGNORECASE | re.UNICODE))
            except re.error:
                return kw_norm.lower() in text_norm.lower()

        # Default: "whole_word" (Bangla + English smart boundary matching from DrawSystem test_regex.php)
        escaped = re.escape(kw_norm)
        pattern = rf"(?<![{WORD_CHAR_CLASS}]){escaped}(?![{WORD_CHAR_CLASS}])"
        return bool(re.search(pattern, text_norm, flags=re.IGNORECASE | re.UNICODE))

    @classmethod
    def evaluate_inline_boolean_query(cls, texts: List[str], expr: str, match_mode: str = "whole_word") -> bool:
        """
        Evaluates an inline boolean expression with `AND`, `OR`, `NOT`, parentheses, and quotes, e.g.:
          `(apple OR আপেল) AND 4 NOT fake`
          `"right answer" OR সঠিক`
        against a participant's list of comment/share texts (returns True if any single comment
        or the combined text satisfies the boolean expression).
        """
        if not expr or not expr.strip():
            return True
        if not texts:
            return False

        tokens = cls._tokenize_boolean_expr(expr)
        if not tokens:
            return True

        # Check each individual comment first, plus combined text for multi-comment participants
        candidate_texts = list(texts)
        if len(texts) > 1:
            candidate_texts.append(" | ".join(texts))

        for single_text in candidate_texts:
            if cls._eval_tokens_for_text(tokens, single_text, match_mode):
                return True
        return False

    @staticmethod
    def _tokenize_boolean_expr(expr: str) -> List[str]:
        token_re = re.compile(
            r'\s*(?:(\()|(\))|("[^"]+"|\'[^\']+\')|\b(AND|OR|NOT)\b|([^\s()]+))',
            re.IGNORECASE | re.UNICODE,
        )
        tokens: List[str] = []
        pos = 0
        while pos < len(expr):
            m = token_re.match(expr, pos)
            if not m:
                break
            lparen, rparen, quoted, op, word = m.groups()
            if lparen:
                tokens.append("(")
            elif rparen:
                tokens.append(")")
            elif quoted:
                tokens.append(quoted[1:-1])
            elif op:
                tokens.append(op.upper())
            elif word:
                # Strip trailing comma if user mixed commas with AND/OR
                w_clean = word.strip(",")
                if w_clean:
                    tokens.append(w_clean)
            pos = m.end()
        return tokens

    @classmethod
    def _eval_tokens_for_text(cls, tokens: List[str], text: str, match_mode: str) -> bool:
        """
        Recursive-descent parser for Boolean expressions:
          Expr   := OrExpr
          OrExpr := AndExpr ( 'OR' AndExpr )*
          AndExpr:= NotExpr ( ['AND'] NotExpr )*
          NotExpr:= 'NOT' NotExpr | Primary
          Primary:= '(' Expr ')' | TERM
        """
        idx = 0
        n = len(tokens)

        def parse_or() -> bool:
            nonlocal idx
            val = parse_and()
            while idx < n and tokens[idx] == "OR":
                idx += 1
                rhs = parse_and()
                val = val or rhs
            return val

        def parse_and() -> bool:
            nonlocal idx
            val = parse_not()
            while idx < n and tokens[idx] not in ("OR", ")"):
                if tokens[idx] == "AND":
                    idx += 1
                    if idx >= n:
                        break
                rhs = parse_not()
                val = val and rhs
            return val

        def parse_not() -> bool:
            nonlocal idx
            if idx < n and tokens[idx] == "NOT":
                idx += 1
                return not parse_not()
            return parse_primary()

        def parse_primary() -> bool:
            nonlocal idx
            if idx >= n:
                return True
            tok = tokens[idx]
            if tok == "(":
                idx += 1
                val = parse_or()
                if idx < n and tokens[idx] == ")":
                    idx += 1
                return val
            if tok in (")", "AND", "OR"):
                idx += 1
                return True
            idx += 1
            return cls.match_single_keyword(text, tok, match_mode)

        try:
            return parse_or()
        except Exception:
            return False

    @classmethod
    def _get_participant_texts(cls, p: ContestParticipant, include_share_text: bool = True) -> List[str]:
        texts = [c for c in p.comment_texts if c and c.strip()]
        if include_share_text and p.share_contents:
            for s in p.share_contents:
                if s and s.strip() and s not in texts:
                    texts.append(s)
        return texts

    @classmethod
    def evaluate_participant(
        cls,
        p: ContestParticipant,
        config: AdvancedFilterConfig,
        duplicate_names: Set[str],
        disqualified_keys: Set[str],
    ) -> ParticipantEvaluation:
        ev = ParticipantEvaluation()
        ev.is_disqualified = p.normalized_key in disqualified_keys
        norm_name = normalize_text(p.name or "").lower().strip()
        ev.is_duplicate_name = norm_name in duplicate_names
        ev.detected_gender = cls.detect_gender(p.name)

        texts = cls._get_participant_texts(p, include_share_text=config.include_share_text)
        ev.has_comment = len(p.comment_texts) > 0 or (config.include_share_text and len(p.share_contents) > 0)

        # Check if all texts are emoji-only / punctuation-only (or no comment)
        meaningful_texts = [t for t in texts if cls.is_valid_meaningful_text(t)]
        ev.is_invalid_emoji_only = bool(ev.has_comment and len(meaningful_texts) == 0)

        or_list = cls.parse_keyword_list(config.or_keywords)
        and_list = cls.parse_keyword_list(config.and_keywords)
        not_list = cls.parse_keyword_list(config.not_keywords)
        has_kw_rules = config.has_active_keyword_rules()

        # 1. Evaluate NOT / Wrong Answer keywords first (matching DrawSystem's WinnerSelectionService)
        if not_list:
            ev.matches_not_excluded = any(
                cls.match_single_keyword(t, bad_kw, config.match_mode)
                for t in texts
                for bad_kw in not_list
            )
        else:
            ev.matches_not_excluded = False

        # 2. Evaluate OR keywords (Match ANY right answer variation)
        if or_list:
            # If user typed inline boolean syntax (AND / NOT) inside the OR box, support it seamlessly
            if any(op in config.or_keywords.upper().split() for op in ("AND", "OR", "NOT")) and "," not in config.or_keywords:
                ev.matches_or = cls.evaluate_inline_boolean_query(texts, config.or_keywords, config.match_mode)
            else:
                ev.matches_or = any(
                    cls.match_single_keyword(t, ok_kw, config.match_mode)
                    for t in texts
                    for ok_kw in or_list
                )
        else:
            ev.matches_or = True

        # 3. Evaluate AND keywords (Must contain ALL keywords across participant's comment/share text)
        if and_list:
            combined_text = " | ".join(texts)
            ev.matches_and = bool(texts) and all(
                any(cls.match_single_keyword(t, req_kw, config.match_mode) for t in texts)
                or cls.match_single_keyword(combined_text, req_kw, config.match_mode)
                for req_kw in and_list
            )
        else:
            ev.matches_and = True

        # 4. Evaluate optional inline boolean expression query
        if config.boolean_query and config.boolean_query.strip():
            ev.matches_boolean_query = cls.evaluate_inline_boolean_query(
                texts, config.boolean_query, config.match_mode
            )
        else:
            ev.matches_boolean_query = True

        # 5. Evaluate Content Length & Word Count rules
        if config.min_comment_length > 0:
            max_len = max((len(t.strip()) for t in texts), default=0)
            ev.matches_length = max_len >= config.min_comment_length
        if config.min_word_count > 0:
            max_words = max((len(t.strip().split()) for t in texts), default=0)
            ev.matches_length = ev.matches_length and (max_words >= config.min_word_count)

        # 6. Evaluate @Mention / #Hashtag requirement
        if config.require_mention_or_hashtag:
            ev.matches_mention_hashtag = any(
                ("@" in t or "#" in t) for t in texts
            )

        # 7. Evaluate Gender filter
        g_filter = (config.gender_filter or "all").lower().strip()
        if g_filter and g_filter != "all":
            ev.matches_gender = ev.detected_gender == g_filter

        # 8. Determine Correct Answer vs Wrong Answer (DrawSystem classification)
        keyword_pass = (
            (not ev.matches_not_excluded)
            and ev.matches_or
            and ev.matches_and
            and ev.matches_boolean_query
        )

        if has_kw_rules:
            ev.is_correct_answer = bool(ev.has_comment and not ev.is_invalid_emoji_only and keyword_pass)
            ev.is_wrong_answer = bool(
                ev.has_comment
                and not ev.is_invalid_emoji_only
                and not keyword_pass
            )
        else:
            # When no specific keyword is typed, any valid non-emoji comment is considered a valid answer
            ev.is_correct_answer = bool(ev.has_comment and not ev.is_invalid_emoji_only)
            ev.is_wrong_answer = False

        # 9. Combine all active rule constraints
        emoji_ok = not (config.exclude_invalid_emoji and (ev.is_invalid_emoji_only or not ev.has_comment))
        ev.passes_all_custom_rules = (
            keyword_pass
            and (not has_kw_rules or ev.has_comment)
            and emoji_ok
            and ev.matches_length
            and ev.matches_mention_hashtag
            and ev.matches_gender
        )

        ev.is_qualified_winner = (
            p.is_eligible
            and ev.passes_all_custom_rules
            and not ev.is_disqualified
        )

        # Build human-readable status badge for the Contest Status column
        if ev.is_disqualified:
            ev.reason_badge = "🚫 DISQUALIFIED"
        elif ev.matches_not_excluded:
            ev.reason_badge = "❌ WRONG ANSWER (Excluded NOT)"
        elif has_kw_rules and not (ev.matches_or and ev.matches_and and ev.matches_boolean_query):
            ev.reason_badge = "❌ WRONG ANSWER (Keyword Miss)"
        elif config.exclude_invalid_emoji and ev.is_invalid_emoji_only:
            ev.reason_badge = "⚠️ INVALID (Emoji-Only)"
        elif not ev.matches_length:
            ev.reason_badge = "⚠️ TOO SHORT"
        elif not ev.matches_mention_hashtag:
            ev.reason_badge = "⚠️ NO @MENTION/#TAG"
        elif not ev.matches_gender:
            ev.reason_badge = f"⚧ GENDER ({ev.detected_gender.upper()})"
        elif ev.is_qualified_winner:
            if config.has_any_rule_constraints():
                ev.reason_badge = "✅ QUALIFIED (3/3 + RULES ✓)"
            else:
                ev.reason_badge = "ELIGIBLE (3/3)"
        else:
            ev.reason_badge = p.status_label

        return ev

    @classmethod
    def evaluate_all(
        cls,
        participants: List[ContestParticipant],
        config: AdvancedFilterConfig,
        disqualified_keys: Optional[Set[str]] = None,
    ) -> Tuple[List[ContestParticipant], Dict[str, ParticipantEvaluation], Dict[str, int]]:
        """
        Evaluates all participants, updates serial numbers (#0001, #0002...) for qualified winners,
        returns:
          - filtered_participants (matching `config.quick_category` and active rules)
          - evaluations_by_key (`p.normalized_key -> ParticipantEvaluation`)
          - category_counts (`all`, `qualified`, `correct`, `wrong`, `invalid`, `no_comments`, `duplicates`, `disqualified`)
        """
        dq_keys = disqualified_keys or set()

        # Identify duplicate normalized names across participants
        name_freq: Dict[str, int] = {}
        for p in participants:
            nm = normalize_text(p.name or "").lower().strip()
            if nm:
                name_freq[nm] = name_freq.get(nm, 0) + 1
        duplicate_names = {nm for nm, count in name_freq.items() if count > 1}

        evals: Dict[str, ParticipantEvaluation] = {}
        counts = {
            "all": len(participants),
            "qualified": 0,
            "correct": 0,
            "wrong": 0,
            "invalid": 0,
            "no_comments": 0,
            "duplicates": 0,
            "disqualified": 0,
        }

        for p in participants:
            ev = cls.evaluate_participant(p, config, duplicate_names, dq_keys)
            evals[p.normalized_key] = ev
            if ev.is_qualified_winner:
                counts["qualified"] += 1
            if ev.is_correct_answer:
                counts["correct"] += 1
            if ev.is_wrong_answer:
                counts["wrong"] += 1
            if ev.is_invalid_emoji_only:
                counts["invalid"] += 1
            if not ev.has_comment:
                counts["no_comments"] += 1
            if ev.is_duplicate_name:
                counts["duplicates"] += 1
            if ev.is_disqualified:
                counts["disqualified"] += 1

        # Re-assign sequential Contest Serial Numbers (#0001, #0002...) to Qualified Winners
        serial = 1
        for p in participants:
            ev = evals[p.normalized_key]
            if ev.is_qualified_winner:
                p.serial_number = serial
                serial += 1
            else:
                p.serial_number = None

        # Filter participants according to active quick_category pill + rule constraints
        cat = (config.quick_category or "all").lower().strip()
        filtered: List[ContestParticipant] = []
        for p in participants:
            ev = evals[p.normalized_key]
            if cat == "qualified":
                if ev.is_qualified_winner:
                    filtered.append(p)
            elif cat == "correct":
                if ev.is_correct_answer and ev.matches_length and ev.matches_mention_hashtag and ev.matches_gender and not ev.is_disqualified:
                    filtered.append(p)
            elif cat == "wrong":
                if ev.is_wrong_answer:
                    filtered.append(p)
            elif cat == "invalid":
                if ev.is_invalid_emoji_only:
                    filtered.append(p)
            elif cat == "no_comments":
                if not ev.has_comment:
                    filtered.append(p)
            elif cat == "duplicates":
                if ev.is_duplicate_name:
                    filtered.append(p)
            elif cat == "disqualified":
                if ev.is_disqualified:
                    filtered.append(p)
            else:
                # "all" category: if user typed active keyword/length/gender rules, filter to matching participants
                # unless they haven't set any rule constraints (in which case show all participants)
                if config.has_any_rule_constraints():
                    if ev.passes_all_custom_rules and not ev.is_disqualified:
                        filtered.append(p)
                else:
                    filtered.append(p)

        return filtered, evals, counts

