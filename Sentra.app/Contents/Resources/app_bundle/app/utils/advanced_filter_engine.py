import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from app.models.share_profile import ContestParticipant
from app.utils.text_normalizer import normalize_text

# Any English letter, digit, or Bengali Unicode character (\u0980-\u09FF)
VALID_CONTENT_RE = re.compile(r"[a-zA-Z0-9\u0980-\u09FF]")
WORD_CHAR_CLASS = r"a-zA-Z0-9\u0980-\u09FF"
PUNCT_STRIP_RE = re.compile(r"^[^\w\u0980-\u09FF]+|[^\w\u0980-\u09FF]+$", re.UNICODE)
BN_TO_EN_DIGIT_MAP = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Sentiment word lists from DrawSystem analyzer.blade.php + Bangla equivalents
POSITIVE_SENTIMENT_WORDS: Set[str] = {
    "good", "great", "awesome", "nice", "love", "amazing", "best", "excellent",
    "fantastic", "perfect", "thanks", "thank you", "alhamdulillah", "mashallah",
    "mashaallah", "subhanallah", "inshallah", "inshaallah", "super", "wonderful",
    "helpful", "congratulations", "congrats", "ready", "done",
    "আলহামদুলিল্লাহ", "মাশাল্লাহ", "মাশাআল্লাহ", "ইনশাআল্লাহ", "সুবহানাল্লাহ",
    "অসাধারণ", "দারুণ", "চমৎকার", "ভালো", "সুন্দর", "ধন্যবাদ", "রেডি", "ডান",
    "অভিনন্দন", "শুভকামনা", "সফল", "বেস্ট",
}

NEGATIVE_SENTIMENT_WORDS: Set[str] = {
    "bad", "fake", "scam", "terrible", "awful", "worst", "hate", "poor",
    "bullshit", "lie", "fraud", "cheat", "spam", "useless", "boring",
    "ভুয়া", "ভুয়া", "প্রতারণা", "খারাপ", "বাজে", "ফালতু", "মিথ্যা", "ধোঁকাবাজি",
}

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
    "সাদেক", "সৈকত", "সজল", "সম্রাট", "স্বপন", "শাকিল", "শ্যামল", "শিমুল",
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
class CustomAnalysisRule:
    """
    Represents a user-created custom intelligence rule from DrawSystem's Analyzer
    (`analyzer.blade.php` / `AnalysisRule.php`).
    Supported `rule_type` values:
      - "keyword_match": Comment contains any of comma-separated keywords (OR)
      - "keyword_all": Comment contains all of comma-separated keywords (AND)
      - "keyword_exact": Comment strictly equals one of comma-separated keywords
      - "keyword_exclude": Comment does NOT contain any of comma-separated keywords (NOT)
      - "regex_match": Comment matches custom Regex pattern
      - "length_greater": Comment character length >= X
      - "has_tags": Comment contains @mention or #hashtag
      - "action_combo": Participant satisfies custom Like/Comment/Share boolean formula
    """
    id: str
    name: str
    rule_type: str
    value: str = ""
    enforce_for_qualification: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rule_type": self.rule_type,
            "value": self.value,
            "enforce_for_qualification": self.enforce_for_qualification,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CustomAnalysisRule":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "Rule")),
            rule_type=str(d.get("rule_type", "keyword_match")),
            value=str(d.get("value", "")),
            enforce_for_qualification=bool(d.get("enforce_for_qualification", True)),
        )


@dataclass
class AdvancedFilterConfig:
    """
    Configuration for Advanced Contest Filtering with:
      1. Interactive Action Requirement Toggle Bar (`👍 Like`, `💬 Comment`, `🔄 Share` with `AND` / `OR` / Custom Formula)
      2. Keyword Boolean Logic (`OR` Right Answers, `AND` Required Words, `NOT` Wrong Answers, Exact Right/Wrong)
      3. Content & Demographic Rules (Min Length, Min Words, Emoji-Only Exclusion, @Mentions/#Tags, Gender, Sentiment)
      4. Dynamic Custom Analysis Rules (`CustomAnalysisRule` list)
    """
    # --- 1. Action Requirement Toggle Bar ---
    require_like: bool = True
    require_comment: bool = True
    require_share: bool = True
    action_operator: str = "AND"     # "AND" | "OR" | "LIKE_AND_COMMENT_OR_SHARE" | "COMMENT_AND_LIKE_OR_SHARE" | "MIN_2_OF_3"

    # --- 1B. 3-Field Chained Action Toggle Bar: [Field 1] [Op 1] [Field 2] [Op 2] [Field 3] ---
    use_action_chain: bool = False
    act_f1_enabled: bool = True
    act_f1_val: str = "like"         # "like" | "comment" | "share" | "not_like" | "not_comment" | "not_share" | "none"
    act_op1: str = "AND"             # "AND" | "OR" | "NOT" | "OR_NOT"
    act_f2_enabled: bool = True
    act_f2_val: str = "comment"
    act_op2: str = "AND"             # "AND" | "OR" | "NOT" | "OR_NOT"
    act_f3_enabled: bool = True
    act_f3_val: str = "share"
    act_group_right: bool = False    # False = (F1 op1 F2) op2 F3 ; True = F1 op1 (F2 op2 F3)

    # --- 2. Keyword & Answer Filtering (DrawSystem + Boolean Logic) ---
    or_keywords: str = ""            # Group 1 (OR): Match ANY of these right answers / keywords
    and_keywords: str = ""           # Group 2 (AND): Must contain ALL of these keywords
    not_keywords: str = ""           # Group 3 (NOT): Wrong answers / excluded spam keywords
    exact_keywords: str = ""         # DrawSystem Exact Required Keyword (overrides partial OR if set)
    exact_wrong_keywords: str = ""   # DrawSystem Exact Wrong Keyword
    boolean_query: str = ""          # Optional inline boolean query e.g. "(ready OR রেডি) AND NOT fake"
    match_mode: str = "whole_word"   # "whole_word" | "contains" | "exact" | "regex"

    # --- 2B. 3-Field Chained Keyword Filter Bar: [Field 1] [Op 1] [Field 2] [Op 2] [Field 3] ---
    use_keyword_chain: bool = False
    kw_f1_enabled: bool = True
    kw_f1_text: str = ""
    kw_op1: str = "AND"              # "AND" | "OR" | "NOT" | "OR_NOT"
    kw_f2_enabled: bool = True
    kw_f2_text: str = ""
    kw_op2: str = "NOT"              # "AND" | "OR" | "NOT" | "OR_NOT"
    kw_f3_enabled: bool = True
    kw_f3_text: str = ""
    kw_group_right: bool = False     # False = (F1 op1 F2) op2 F3 ; True = F1 op1 (F2 op2 F3)

    # --- 3. Content, Demographic & Sentiment Rules ---
    min_comment_length: int = 0      # Minimum comment character length
    min_word_count: int = 0          # Minimum comment word count
    exclude_invalid_emoji: bool = False  # Reject comments that only have emojis/punctuation
    require_mention_or_hashtag: bool = False  # Require @mention or #hashtag
    gender_filter: str = "all"       # "all" | "male" | "female" | "unknown"
    sentiment_filter: str = "all"    # "all" | "positive" | "neutral" | "negative"
    one_entry_per_user: bool = False # Deduplicate by normalized name when picking winners
    quick_category: str = "all"      # "all" | "qualified" | "correct" | "wrong" | "invalid" | "no_comments" | "duplicates" | "disqualified"
    include_share_text: bool = True  # Check share_contents in addition to comment_texts

    # --- 4. Dynamic Custom Analysis Rules (DrawSystem Analyzer) ---
    custom_rules: List[CustomAnalysisRule] = field(default_factory=list)

    def has_active_keyword_rules(self) -> bool:
        if self.use_keyword_chain:
            return bool(
                (self.kw_f1_enabled and self.kw_f1_text.strip())
                or (self.kw_f2_enabled and self.kw_f2_text.strip())
                or (self.kw_f3_enabled and self.kw_f3_text.strip())
            )
        return bool(
            self.or_keywords.strip()
            or self.and_keywords.strip()
            or self.not_keywords.strip()
            or self.exact_keywords.strip()
            or self.exact_wrong_keywords.strip()
            or self.boolean_query.strip()
        )

    def has_custom_action_toggle(self) -> bool:
        if self.use_action_chain:
            s1 = self.act_f1_enabled and self.act_f1_val not in ("none", "")
            s2 = self.act_f2_enabled and self.act_f2_val not in ("none", "")
            s3 = self.act_f3_enabled and self.act_f3_val not in ("none", "")
            is_default_3 = (
                s1 and s2 and s3
                and {self.act_f1_val, self.act_f2_val, self.act_f3_val} == {"like", "comment", "share"}
                and self.act_op1.upper() == "AND"
                and self.act_op2.upper() == "AND"
            )
            return not is_default_3
        return not (
            self.require_like
            and self.require_comment
            and self.require_share
            and self.action_operator == "AND"
        )

    def has_content_or_demographic_constraints(self) -> bool:
        return bool(
            self.has_active_keyword_rules()
            or self.min_comment_length > 0
            or self.min_word_count > 0
            or self.exclude_invalid_emoji
            or self.require_mention_or_hashtag
            or self.gender_filter not in ("all", "")
            or self.sentiment_filter not in ("all", "")
            or any(r.enforce_for_qualification for r in self.custom_rules)
        )

    def has_any_rule_constraints(self) -> bool:
        return bool(
            self.has_custom_action_toggle()
            or self.has_content_or_demographic_constraints()
        )

    @staticmethod
    def _format_action_val(val: str) -> str:
        mapping = {
            "like": "✅ Reaction",
            "reaction": "✅ Reaction",
            "comment": "✅ Comment",
            "share": "✅ Share",
            "not_like": "❌ NOT Reaction",
            "not_reaction": "❌ NOT Reaction",
            "not_comment": "❌ NOT Comment",
            "not_share": "❌ NOT Share",
        }
        return mapping.get((val or "").lower().strip(), val)

    @staticmethod
    def _format_chain_formula(
        slots: List[Tuple[bool, str]],
        op1: str,
        op2: str,
        group_right: bool = False,
        empty_label: str = "None",
    ) -> str:
        s1_on, s1_txt = slots[0]
        s2_on, s2_txt = slots[1]
        s3_on, s3_txt = slots[2]
        o1 = (op1 or "AND").upper().replace("_", " ")
        o2 = (op2 or "AND").upper().replace("_", " ")

        if s1_on and s2_on and s3_on:
            if o1 == o2:
                return f"{s1_txt} {o1} {s2_txt} {o2} {s3_txt}"
            if group_right:
                return f"{s1_txt} {o1} ({s2_txt} {o2} {s3_txt})"
            return f"({s1_txt} {o1} {s2_txt}) {o2} {s3_txt}"
        if s1_on and s2_on:
            return f"{s1_txt} {o1} {s2_txt}"
        if s1_on and s3_on:
            return f"{s1_txt} {o2} {s3_txt}"
        if s2_on and s3_on:
            prefix = "NOT " if o1 in ("NOT", "AND NOT") else ""
            return f"{prefix}{s2_txt} {o2} {s3_txt}"
        if s1_on:
            return s1_txt
        if s2_on:
            prefix = "NOT " if o1 in ("NOT", "AND NOT") else ""
            return f"{prefix}{s2_txt}"
        if s3_on:
            prefix = "NOT " if o2 in ("NOT", "AND NOT") else ""
            return f"{prefix}{s3_txt}"
        return empty_label

    def describe_action_rule(self) -> str:
        if self.use_action_chain:
            s1 = (self.act_f1_enabled and self.act_f1_val not in ("none", ""), self._format_action_val(self.act_f1_val))
            s2 = (self.act_f2_enabled and self.act_f2_val not in ("none", ""), self._format_action_val(self.act_f2_val))
            s3 = (self.act_f3_enabled and self.act_f3_val not in ("none", ""), self._format_action_val(self.act_f3_val))
            return self._format_chain_formula(
                [s1, s2, s3],
                self.act_op1,
                self.act_op2,
                self.act_group_right,
                empty_label="Any Participant (No Action Required)",
            )

        op = (self.action_operator or "AND").upper()
        if op == "LIKE_AND_COMMENT_OR_SHARE":
            return "Like 👍 AND (Comment 💬 OR Share 🔄)"
        if op == "COMMENT_AND_LIKE_OR_SHARE":
            return "Comment 💬 AND (Like 👍 OR Share 🔄)"
        if op == "SHARE_AND_LIKE_OR_COMMENT":
            return "Share 🔄 AND (Like 👍 OR Comment 💬)"
        if op == "MIN_2_OF_3":
            return "Any 2 of 3 Actions (2/3+)"

        selected = []
        if self.require_like:
            selected.append("Like 👍")
        if self.require_comment:
            selected.append("Comment 💬")
        if self.require_share:
            selected.append("Share 🔄")
        if not selected:
            return "Any Participant (No Action Required)"

        if op == "OR":
            return " OR ".join(selected)
        return " AND ".join(selected)

    def describe_keyword_rule(self) -> str:
        if self.use_keyword_chain:
            s1 = (self.kw_f1_enabled and bool(self.kw_f1_text.strip()), f"[{self.kw_f1_text.strip()}]")
            s2 = (self.kw_f2_enabled and bool(self.kw_f2_text.strip()), f"[{self.kw_f2_text.strip()}]")
            s3 = (self.kw_f3_enabled and bool(self.kw_f3_text.strip()), f"[{self.kw_f3_text.strip()}]")
            return self._format_chain_formula(
                [s1, s2, s3],
                self.kw_op1,
                self.kw_op2,
                self.kw_group_right,
                empty_label="",
            )
        parts = []
        if self.or_keywords.strip():
            parts.append(f"OR: {self.or_keywords.strip()}")
        if self.and_keywords.strip():
            parts.append(f"AND: {self.and_keywords.strip()}")
        if self.not_keywords.strip():
            parts.append(f"NOT: {self.not_keywords.strip()}")
        return " | ".join(parts)

    def describe_full_rules(self) -> str:
        parts = [self.describe_action_rule()]
        kw_desc = self.describe_keyword_rule()
        if kw_desc:
            parts.append(f"Keywords: {kw_desc}")
        if self.min_comment_length > 0:
            parts.append(f"Min {self.min_comment_length} chars")
        if self.min_word_count > 0:
            parts.append(f"Min {self.min_word_count} words")
        if self.exclude_invalid_emoji:
            parts.append("No Emoji-Only")
        if self.require_mention_or_hashtag:
            parts.append("@Mention/#Tag")
        if self.gender_filter not in ("all", ""):
            parts.append(f"Gender: {self.gender_filter.title()}")
        if self.sentiment_filter not in ("all", ""):
            parts.append(f"Sentiment: {self.sentiment_filter.title()}")
        if self.one_entry_per_user:
            parts.append("1 Entry/Person")
        enforced_rules = [r.name for r in self.custom_rules if r.enforce_for_qualification]
        if enforced_rules:
            parts.append(f"Custom Rules: {', '.join(enforced_rules)}")
        return " | ".join(parts)


@dataclass
class ParticipantEvaluation:
    """
    Stores the computed FairDraw / DrawSystem evaluation state for a single ContestParticipant.
    """
    passes_action_rule: bool = True
    missing_selected_actions: List[str] = field(default_factory=list)
    has_comment: bool = False
    is_invalid_emoji_only: bool = False
    matches_or: bool = True
    matches_and: bool = True
    matches_not_excluded: bool = False  # True if disqualified by NOT / Wrong keyword
    matches_boolean_query: bool = True
    matches_length: bool = True
    matches_mention_hashtag: bool = True
    matches_gender: bool = True
    matches_sentiment: bool = True
    matches_custom_rules: bool = True
    custom_rule_results: Dict[str, bool] = field(default_factory=dict)
    detected_gender: str = "unknown"    # "male" | "female" | "unknown"
    detected_sentiment: str = "neutral" # "positive" | "neutral" | "negative"
    is_duplicate_name: bool = False
    is_disqualified: bool = False
    is_correct_answer: bool = False
    is_wrong_answer: bool = False
    passes_all_custom_rules: bool = True
    is_qualified_winner: bool = False   # passes_action_rule + passes_all_custom_rules + not disqualified
    reason_badge: str = ""


class AdvancedFilterEngine:
    """
    Evaluates ContestParticipants against DrawSystem's advanced filtering rules + Action Toggle Bar:
    - Interactive Action Requirement Toggle (`Like`, `Comment`, `Share` with `AND`, `OR`, `Like & (Comment OR Share)`, `Comment & (Like OR Share)`, `Any 2 of 3`)
    - Boolean `OR` (Any right answer), `AND` (All required keywords), `NOT` (Wrong answers / Exclude)
    - DrawSystem `Exact Required Keyword` & `Exact Wrong Keyword`
    - Inline Boolean Expression parser (`(apple OR আপেল) AND fresh NOT rotten`)
    - Unicode Bangla + English Whole-Word Boundary matching (`4` != `14`, `ভালো` != `ভালোবাসি`)
    - Emoji-only / Invalid comment detection (`![a-zA-Z0-9\\u0980-\\u09FF]`)
    - Gender & Sentiment detection (`Male`, `Female`, `Unknown`; `Positive`, `Neutral`, `Negative`)
    - Dynamic Custom Analysis Rules (`CustomAnalysisRule` columns)
    - Live Category Pill counts & percentages (`All`, `Qualified`, `Correct`, `Wrong`, `Invalid`, `No Comments`, `Duplicates`, `Disqualified`)
    """

    @staticmethod
    def parse_keyword_list(raw: str) -> List[str]:
        if not raw or not raw.strip():
            return []
        parts = re.split(r"[,;\n]+", raw)
        return [p.strip() for p in parts if p.strip()]

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
        using DrawSystem's token dictionary (`ParticipantImportService.php` & `GenderDictionaryController.php`).
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

    @staticmethod
    def detect_sentiment(texts: List[str]) -> str:
        """
        Detects 'positive', 'negative', or 'neutral' sentiment from participant comments
        matching DrawSystem's Global Analyzer (`analyzer.blade.php` lines 316-322).
        """
        if not texts:
            return "neutral"
        combined = " ".join(texts).lower()
        has_pos = any(w in combined for w in POSITIVE_SENTIMENT_WORDS)
        has_neg = any(w in combined for w in NEGATIVE_SENTIMENT_WORDS)
        if has_pos and not has_neg:
            return "positive"
        if has_neg and not has_pos:
            return "negative"
        return "neutral"

    @staticmethod
    def _apply_bool_op(lhs: bool, op: str, rhs: bool) -> bool:
        o = (op or "AND").upper().strip().replace(" ", "_")
        if o == "OR":
            return lhs or rhs
        if o in ("NOT", "AND_NOT"):
            return lhs and (not rhs)
        if o == "OR_NOT":
            return lhs or (not rhs)
        return lhs and rhs

    @classmethod
    def evaluate_three_slot_chain(
        cls,
        slots: List[Tuple[bool, bool]],
        op1: str,
        op2: str,
        group_right: bool = False,
    ) -> bool:
        """
        Evaluates a 3-slot chain `[Field 1] [Op 1] [Field 2] [Op 2] [Field 3]` where each
        slot is `(is_selected, slot_bool_value)`.
        If a slot is NOT selected (`is_selected == False`), that slot and its connecting operator
        are NOT applied!
        """
        s1_on, v1 = slots[0]
        s2_on, v2 = slots[1]
        s3_on, v3 = slots[2]
        o1 = (op1 or "AND").upper().strip().replace(" ", "_")
        o2 = (op2 or "AND").upper().strip().replace(" ", "_")

        if s1_on and s2_on and s3_on:
            if group_right:
                r23 = cls._apply_bool_op(v2, o2, v3)
                return cls._apply_bool_op(v1, o1, r23)
            r12 = cls._apply_bool_op(v1, o1, v2)
            return cls._apply_bool_op(r12, o2, v3)

        if s1_on and s2_on:
            # 3rd field is NOT selected -> not applied!
            return cls._apply_bool_op(v1, o1, v2)

        if s1_on and s3_on:
            # 2nd field is NOT selected -> combine Field 1 and Field 3 via Op 2
            return cls._apply_bool_op(v1, o2, v3)

        if s2_on and s3_on:
            # 1st field is NOT selected -> start at Field 2 (invert if Op 1 is NOT) and combine with Field 3 via Op 2
            start2 = (not v2) if o1 in ("NOT", "AND_NOT") else v2
            return cls._apply_bool_op(start2, o2, v3)

        if s1_on:
            return v1
        if s2_on:
            return (not v2) if o1 in ("NOT", "AND_NOT") else v2
        if s3_on:
            return (not v3) if o2 in ("NOT", "AND_NOT") else v3

        return True

    @staticmethod
    def _eval_single_action_slot(p: ContestParticipant, val: str) -> Tuple[bool, str]:
        v = (val or "").lower().strip()
        if v in ("like", "reaction"):
            return bool(p.liked), "Reaction"
        if v == "comment":
            return bool(p.commented), "Comment"
        if v == "share":
            return bool(p.shared), "Share"
        if v in ("not_like", "not_reaction"):
            return not bool(p.liked), "NOT Reaction"
        if v == "not_comment":
            return not bool(p.commented), "NOT Comment"
        if v == "not_share":
            return not bool(p.shared), "NOT Share"
        return True, ""

    @classmethod
    def evaluate_keyword_slot(cls, text_or_texts, raw_kw: str, match_mode: str = "whole_word") -> bool:
        """
        Evaluates a single Keyword Field slot (e.g. Field 1, Field 2, or Field 3) against
        either a single string (`str`) or a list of strings (`List[str]`).
        Supports:
          - Comma-separated synonyms (matches if ANY synonym appears)
          - Inline boolean queries (`(apple OR আপেল) AND fresh NOT fake`)
        """
        if isinstance(text_or_texts, str):
            texts = [text_or_texts] if text_or_texts.strip() else []
        else:
            texts = [t for t in (text_or_texts or []) if t and t.strip()]

        if not raw_kw or not raw_kw.strip():
            return True
        if not texts:
            return False

        kws = cls.parse_keyword_list(raw_kw)
        if not kws:
            return True

        # Check if user typed an inline boolean operator inside a single keyword box
        if any(op in raw_kw.upper().split() for op in ("AND", "OR", "NOT")) and "," not in raw_kw:
            return cls.evaluate_inline_boolean_query(texts, raw_kw, match_mode)

        return any(
            cls.match_single_keyword(t, kw, match_mode)
            for t in texts
            for kw in kws
        )

    @classmethod
    def evaluate_action_requirement(cls, p: ContestParticipant, config: AdvancedFilterConfig) -> Tuple[bool, List[str]]:
        """
        Evaluates whether participant `p` satisfies the interactive Action Toggle Bar:
          - Supports the 3-Field Chained Action Bar: `[Field 1] [Op 1] [Field 2] [Op 2] [Field 3]`
            where unselected fields are ignored.
          - Also supports preset/legacy operators (`AND`, `OR`, `LIKE_AND_COMMENT_OR_SHARE`, etc.).
        Returns `(passes, missing_action_names)`.
        """
        if config.use_action_chain:
            s1_on = bool(config.act_f1_enabled and config.act_f1_val not in ("none", ""))
            s2_on = bool(config.act_f2_enabled and config.act_f2_val not in ("none", ""))
            s3_on = bool(config.act_f3_enabled and config.act_f3_val not in ("none", ""))

            v1, lbl1 = cls._eval_single_action_slot(p, config.act_f1_val) if s1_on else (True, "")
            v2, lbl2 = cls._eval_single_action_slot(p, config.act_f2_val) if s2_on else (True, "")
            v3, lbl3 = cls._eval_single_action_slot(p, config.act_f3_val) if s3_on else (True, "")

            o1 = (config.act_op1 or "AND").upper().strip().replace(" ", "_")
            o2 = (config.act_op2 or "AND").upper().strip().replace(" ", "_")

            passed = cls.evaluate_three_slot_chain(
                [(s1_on, v1), (s2_on, v2), (s3_on, v3)],
                config.act_op1,
                config.act_op2,
                config.act_group_right,
            )
            if passed:
                return (True, [])

            missing = []
            if s1_on and not v1 and lbl1:
                missing.append(lbl1)
            if s2_on:
                if o1 in ("NOT", "AND_NOT", "OR_NOT"):
                    if v2 and lbl2:
                        missing.append(f"Excluded: {lbl2}")
                elif not v2 and lbl2 and lbl2 not in missing:
                    missing.append(lbl2)
            if s3_on:
                if o2 in ("NOT", "AND_NOT", "OR_NOT"):
                    if v3 and lbl3:
                        missing.append(f"Excluded: {lbl3}")
                elif not v3 and lbl3 and lbl3 not in missing:
                    missing.append(lbl3)
            return (False, missing)

        op = (config.action_operator or "AND").upper().strip()

        if op == "LIKE_AND_COMMENT_OR_SHARE":
            missing = []
            if not p.liked:
                missing.append("Like")
            if not (p.commented or p.shared):
                missing.append("Comment/Share")
            return (len(missing) == 0, missing)

        if op == "COMMENT_AND_LIKE_OR_SHARE":
            missing = []
            if not p.commented:
                missing.append("Comment")
            if not (p.liked or p.shared):
                missing.append("Like/Share")
            return (len(missing) == 0, missing)

        if op == "SHARE_AND_LIKE_OR_COMMENT":
            missing = []
            if not p.shared:
                missing.append("Share")
            if not (p.liked or p.commented):
                missing.append("Like/Comment")
            return (len(missing) == 0, missing)

        if op == "MIN_2_OF_3":
            passed = p.actions_completed >= 2
            return (passed, [] if passed else p.missing_actions)

        selected_checks: List[Tuple[str, bool]] = []
        if config.require_like:
            selected_checks.append(("Like", bool(p.liked)))
        if config.require_comment:
            selected_checks.append(("Comment", bool(p.commented)))
        if config.require_share:
            selected_checks.append(("Share", bool(p.shared)))

        if not selected_checks:
            return (True, [])

        if op == "OR":
            passed = any(done for _, done in selected_checks)
            missing = [] if passed else [name for name, done in selected_checks if not done]
            return (passed, missing)

        # Default: "AND" across whichever action buttons are toggled ON
        missing = [name for name, done in selected_checks if not done]
        return (len(missing) == 0, missing)

    @classmethod
    def match_single_keyword(cls, text: str, keyword: str, match_mode: str = "whole_word") -> bool:
        """
        Matches a single keyword against a single comment/share string using the selected mode:
        - "contains": Case-insensitive substring match
        - "whole_word": Unicode-aware word boundary for English + Bangla (`test_regex.php`)
        - "exact": Entire comment (stripped of surrounding punctuation/spaces) equals keyword
        - "regex": Custom regular expression
        Also transparently unifies Bangla digits (০-৯) and English digits (0-9) so '4' matches '৪'
        while strictly preserving word boundaries ('4' never matches '14' or '১৪').
        """
        if not text or not keyword:
            return False

        kw = keyword.strip()
        if not kw:
            return False

        text_norm = normalize_text(text)
        kw_norm = normalize_text(kw)
        text_digits = text_norm.translate(BN_TO_EN_DIGIT_MAP)
        kw_digits = kw_norm.translate(BN_TO_EN_DIGIT_MAP)
        mode = (match_mode or "whole_word").lower().strip()

        if mode == "contains":
            return (kw_norm.lower() in text_norm.lower()) or (kw_digits.lower() in text_digits.lower())

        if mode == "exact":
            t_clean = PUNCT_STRIP_RE.sub("", text_digits.strip()).lower()
            k_clean = PUNCT_STRIP_RE.sub("", kw_digits.strip()).lower()
            if not k_clean:
                return text_digits.strip().lower() == kw_digits.strip().lower()
            return t_clean == k_clean

        if mode == "regex":
            try:
                return bool(
                    re.search(kw, text_norm, flags=re.IGNORECASE | re.UNICODE)
                    or re.search(kw_digits, text_digits, flags=re.IGNORECASE | re.UNICODE)
                )
            except re.error:
                return kw_digits.lower() in text_digits.lower()

        # Default: "whole_word" (Bangla + English smart boundary matching from DrawSystem test_regex.php)
        escaped_raw = re.escape(kw_norm)
        pattern_raw = rf"(?<![{WORD_CHAR_CLASS}]){escaped_raw}(?![{WORD_CHAR_CLASS}])"
        if re.search(pattern_raw, text_norm, flags=re.IGNORECASE | re.UNICODE):
            return True
        if kw_digits != kw_norm or text_digits != text_norm:
            escaped_dig = re.escape(kw_digits)
            pattern_dig = rf"(?<![{WORD_CHAR_CLASS}]){escaped_dig}(?![{WORD_CHAR_CLASS}])"
            return bool(re.search(pattern_dig, text_digits, flags=re.IGNORECASE | re.UNICODE))
        return False

    @classmethod
    def evaluate_inline_boolean_query(cls, texts: List[str], expr: str, match_mode: str = "whole_word") -> bool:
        """
        Evaluates an inline boolean expression with `AND`, `OR`, `NOT`, parentheses, and quotes, e.g.:
          `(apple OR আপেল) AND 4 NOT fake`
          `"right answer" OR সঠিক`
        against a participant's list of comment/share texts.
        """
        if not expr or not expr.strip():
            return True
        if not texts:
            return False

        tokens = cls._tokenize_boolean_expr(expr)
        if not tokens:
            return True

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
                w_clean = word.strip(",")
                if w_clean:
                    tokens.append(w_clean)
            pos = m.end()
        return tokens

    @classmethod
    def _eval_tokens_for_text(cls, tokens: List[str], text: str, match_mode: str) -> bool:
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
    def evaluate_custom_rule(cls, p: ContestParticipant, texts: List[str], rule: CustomAnalysisRule) -> bool:
        """
        Evaluates a single CustomAnalysisRule (from DrawSystem's Global Analyzer Rule Builder)
        against a participant.
        """
        rtype = (rule.rule_type or "keyword_match").lower().strip()
        val = (rule.value or "").strip()

        if rtype == "keyword_match":
            kws = cls.parse_keyword_list(val)
            if not kws:
                return True
            return any(cls.match_single_keyword(t, kw, "whole_word") for t in texts for kw in kws)

        if rtype == "keyword_contains":
            kws = cls.parse_keyword_list(val)
            if not kws:
                return True
            return any(cls.match_single_keyword(t, kw, "contains") for t in texts for kw in kws)

        if rtype == "keyword_all":
            kws = cls.parse_keyword_list(val)
            if not kws:
                return True
            combined = " | ".join(texts)
            return bool(texts) and all(
                any(cls.match_single_keyword(t, kw, "whole_word") for t in texts)
                or cls.match_single_keyword(combined, kw, "whole_word")
                for kw in kws
            )

        if rtype == "keyword_exact":
            kws = cls.parse_keyword_list(val)
            if not kws:
                return True
            return any(cls.match_single_keyword(t, kw, "exact") for t in texts for kw in kws)

        if rtype == "keyword_exclude":
            kws = cls.parse_keyword_list(val)
            if not kws:
                return True
            return not any(cls.match_single_keyword(t, kw, "whole_word") for t in texts for kw in kws)

        if rtype == "regex_match":
            if not val:
                return True
            return any(cls.match_single_keyword(t, val, "regex") for t in texts)

        if rtype == "length_greater":
            try:
                min_len = int(val or "0")
            except ValueError:
                min_len = 0
            return max((len(t.strip()) for t in texts), default=0) >= min_len

        if rtype == "has_tags":
            return any(("@" in t or "#" in t) for t in texts)

        if rtype == "boolean_expr":
            return cls.evaluate_inline_boolean_query(texts, val, "whole_word")

        if rtype == "action_combo":
            return cls.evaluate_action_formula(p, val)

        return True

    @classmethod
    def evaluate_action_formula(cls, p: ContestParticipant, expr: str) -> bool:
        """
        Evaluates a custom boolean formula over `like`, `comment`, `share`, e.g.:
          `(like AND comment) OR share`
          `comment AND (like OR share)`
          `like AND NOT share`
        """
        if not expr or not expr.strip():
            return True
        tokens = cls._tokenize_boolean_expr(expr)
        if not tokens:
            return True
        idx = 0
        n = len(tokens)

        def eval_act_token(tok: str) -> bool:
            t_low = tok.lower().strip()
            if t_low in ("like", "liked", "reaction", "reacted", "👍"):
                return bool(p.liked)
            if t_low in ("comment", "commented", "💬"):
                return bool(p.commented)
            if t_low in ("share", "shared", "🔄"):
                return bool(p.shared)
            if t_low in ("2/3", "min2"):
                return p.actions_completed >= 2
            if t_low in ("3/3", "all"):
                return p.actions_completed >= 3
            return False

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
            return eval_act_token(tok)

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

        # 0. Evaluate Action Requirement Toggle Bar (Like / Comment / Share with AND / OR / Custom)
        ev.passes_action_rule, ev.missing_selected_actions = cls.evaluate_action_requirement(p, config)

        texts = cls._get_participant_texts(p, include_share_text=config.include_share_text)
        ev.has_comment = len(p.comment_texts) > 0 or (config.include_share_text and len(p.share_contents) > 0)
        ev.detected_sentiment = cls.detect_sentiment(texts)

        # Check if all texts are emoji-only / punctuation-only (or no comment)
        meaningful_texts = [t for t in texts if cls.is_valid_meaningful_text(t)]
        ev.is_invalid_emoji_only = bool(ev.has_comment and len(meaningful_texts) == 0)

        has_kw_rules = config.has_active_keyword_rules()

        if config.use_keyword_chain:
            k1_on = bool(config.kw_f1_enabled and config.kw_f1_text.strip())
            k2_on = bool(config.kw_f2_enabled and config.kw_f2_text.strip())
            k3_on = bool(config.kw_f3_enabled and config.kw_f3_text.strip())

            b1 = cls.evaluate_keyword_slot(texts, config.kw_f1_text, config.match_mode) if k1_on else True
            b2 = cls.evaluate_keyword_slot(texts, config.kw_f2_text, config.match_mode) if k2_on else True
            b3 = cls.evaluate_keyword_slot(texts, config.kw_f3_text, config.match_mode) if k3_on else True

            o1 = (config.kw_op1 or "AND").upper().strip().replace(" ", "_")
            o2 = (config.kw_op2 or "AND").upper().strip().replace(" ", "_")

            chain_ok = cls.evaluate_three_slot_chain(
                [(k1_on, b1), (k2_on, b2), (k3_on, b3)],
                config.kw_op1,
                config.kw_op2,
                config.kw_group_right,
            )

            # Flag explicit NOT exclusions only when the participant actually failed the chain due to a NOT slot
            not_hit = (not chain_ok) and (
                (k2_on and o1 in ("NOT", "AND_NOT") and b2)
                or (k3_on and o2 in ("NOT", "AND_NOT") and b3)
            )
            ev.matches_not_excluded = bool(not_hit)
            ev.matches_or = chain_ok
            ev.matches_and = chain_ok
            ev.matches_boolean_query = True
            keyword_pass = chain_ok
        else:
            or_list = cls.parse_keyword_list(config.or_keywords)
            and_list = cls.parse_keyword_list(config.and_keywords)
            not_list = cls.parse_keyword_list(config.not_keywords)
            exact_list = cls.parse_keyword_list(config.exact_keywords)
            exact_wrong_list = cls.parse_keyword_list(config.exact_wrong_keywords)

            # 1. Evaluate NOT / Wrong Answer keywords first (matching DrawSystem's WinnerSelectionService)
            if exact_wrong_list:
                ev.matches_not_excluded = any(
                    cls.match_single_keyword(t, bad_kw, "exact")
                    for t in texts
                    for bad_kw in exact_wrong_list
                )
            else:
                ev.matches_not_excluded = False

            if not ev.matches_not_excluded and not_list:
                ev.matches_not_excluded = any(
                    cls.match_single_keyword(t, bad_kw, config.match_mode)
                    for t in texts
                    for bad_kw in not_list
                )

            # 2. Evaluate Exact Required Keywords or OR Keywords (Match ANY right answer variation)
            if exact_list:
                ev.matches_or = any(
                    cls.match_single_keyword(t, ekw, "exact")
                    for t in texts
                    for ekw in exact_list
                )
            elif or_list:
                # Support inline boolean syntax (AND / NOT) if typed directly inside the OR box
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

            keyword_pass = (
                (not ev.matches_not_excluded)
                and ev.matches_or
                and ev.matches_and
                and ev.matches_boolean_query
            )

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

        # 7. Evaluate Gender & Sentiment filters
        g_filter = (config.gender_filter or "all").lower().strip()
        if g_filter and g_filter != "all":
            ev.matches_gender = ev.detected_gender == g_filter

        s_filter = (config.sentiment_filter or "all").lower().strip()
        if s_filter and s_filter != "all":
            ev.matches_sentiment = ev.detected_sentiment == s_filter

        # 8. Evaluate Dynamic Custom Analysis Rules (DrawSystem Analyzer)
        ev.matches_custom_rules = True
        for rule in config.custom_rules:
            res = cls.evaluate_custom_rule(p, texts, rule)
            ev.custom_rule_results[rule.id] = res
            if rule.enforce_for_qualification and not res:
                ev.matches_custom_rules = False

        # 9. Determine Correct Answer vs Wrong Answer (DrawSystem classification)

        if has_kw_rules:
            ev.is_correct_answer = bool(ev.has_comment and not ev.is_invalid_emoji_only and keyword_pass)
            ev.is_wrong_answer = bool(
                ev.has_comment
                and not ev.is_invalid_emoji_only
                and not keyword_pass
            )
        else:
            ev.is_correct_answer = bool(ev.has_comment and not ev.is_invalid_emoji_only)
            ev.is_wrong_answer = False

        # 10. Combine all active content/demographic/custom rule constraints
        emoji_ok = not (config.exclude_invalid_emoji and (ev.is_invalid_emoji_only or not ev.has_comment))
        ev.passes_all_custom_rules = (
            keyword_pass
            and (not has_kw_rules or ev.has_comment)
            and emoji_ok
            and ev.matches_length
            and ev.matches_mention_hashtag
            and ev.matches_gender
            and ev.matches_sentiment
            and ev.matches_custom_rules
        )

        ev.is_qualified_winner = (
            ev.passes_action_rule
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
        elif not ev.matches_sentiment:
            ev.reason_badge = f"💬 SENTIMENT ({ev.detected_sentiment.upper()})"
        elif not ev.matches_custom_rules:
            ev.reason_badge = "❌ FAILED CUSTOM RULE"
        elif not ev.passes_action_rule:
            missing_str = ", ".join(ev.missing_selected_actions) if ev.missing_selected_actions else ", ".join(p.missing_actions)
            ev.reason_badge = f"INCOMPLETE ({p.actions_completed}/3 - Missing: {missing_str})"
        elif ev.is_qualified_winner:
            if config.has_any_rule_constraints():
                ev.reason_badge = f"✅ QUALIFIED ({p.actions_completed}/3 + RULES ✓)"
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
        and returns:
          - filtered_participants (matching `config.quick_category` and active rules)
          - evaluations_by_key (`p.normalized_key -> ParticipantEvaluation`)
          - category_counts (`all`, `qualified`, `correct`, `wrong`, `invalid`, `no_comments`, `duplicates`, `disqualified`,
             plus `male`, `female`, `unknown_gender`, `positive`, `neutral`, `negative`, `unique_names`)
        """
        dq_keys = disqualified_keys or set()

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
            "unique_names": len(name_freq),
            "male": 0,
            "female": 0,
            "unknown_gender": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
        }

        seen_winner_names: Set[str] = set()

        for p in participants:
            ev = cls.evaluate_participant(p, config, duplicate_names, dq_keys)
            # Optional "One Entry Per User" rule from DrawSystem RuleEngine.php
            if config.one_entry_per_user and ev.is_qualified_winner:
                nm = normalize_text(p.name or "").lower().strip()
                if nm and nm in seen_winner_names:
                    ev.is_qualified_winner = False
                    ev.reason_badge = "👥 DUPLICATE ENTRY (1/User)"
                elif nm:
                    seen_winner_names.add(nm)

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

            if ev.detected_gender == "male":
                counts["male"] += 1
            elif ev.detected_gender == "female":
                counts["female"] += 1
            else:
                counts["unknown_gender"] += 1

            if ev.detected_sentiment == "positive":
                counts["positive"] += 1
            elif ev.detected_sentiment == "negative":
                counts["negative"] += 1
            else:
                counts["neutral"] += 1

        # Re-assign sequential Contest Serial Numbers (#0001, #0002...) to Qualified Winners
        serial = 1
        for p in participants:
            ev = evals[p.normalized_key]
            p._eval_status_badge = ev.reason_badge
            p._eval_is_qualified = ev.is_qualified_winner
            if ev.is_qualified_winner:
                p.serial_number = serial
                serial += 1
            else:
                p.serial_number = None

        # Filter participants according to active quick_category pill + rule constraints
        cat = (config.quick_category or "all").lower().strip()
        filtered: List[ContestParticipant] = []
        seen_all_names: Set[str] = set()
        for p in participants:
            ev = evals[p.normalized_key]
            if cat == "qualified":
                if ev.is_qualified_winner:
                    filtered.append(p)
            elif cat == "correct":
                if (
                    ev.is_correct_answer
                    and ev.matches_length
                    and ev.matches_mention_hashtag
                    and ev.matches_gender
                    and ev.matches_sentiment
                    and ev.matches_custom_rules
                    and not ev.is_disqualified
                ):
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
                if config.has_any_rule_constraints() or config.one_entry_per_user:
                    if ev.is_disqualified:
                        continue
                    if config.has_custom_action_toggle() and not ev.passes_action_rule:
                        continue
                    if config.has_content_or_demographic_constraints() and not ev.passes_all_custom_rules:
                        continue
                    if config.one_entry_per_user:
                        nm = normalize_text(p.name or "").lower().strip()
                        if nm and nm in seen_all_names:
                            continue
                        if nm:
                            seen_all_names.add(nm)
                    filtered.append(p)
                else:
                    filtered.append(p)

        # Always sort Qualified Winners (#0001, #0002...) to the top of the table
        filtered.sort(
            key=lambda item: (
                0 if item.serial_number is not None else 1,
                item.serial_number if item.serial_number is not None else 999999999,
                -item.actions_completed,
                item.name.lower(),
                item.disambiguator,
            )
        )

        return filtered, evals, counts
