"""Voice consent V1, step 4: the line rules. The free, deterministic first pass
of every line check, before the check model (app.safety.line_checks).

    check(text) -> RuleResult     verdict pass | block | review, the categories, the rule ids that hit

Keyword and pattern lists per category, in English, Hindi (Devanagari) and
Hinglish (Hindi in Latin letters):

    fraud           asks for an OTP, PIN, password, card, UPI or bank details; "transfer the money now"     block
    impersonation   claims to be a named real person, the police, a bank, a government body                  block
    political       parties, elections, voting instructions                                                block
    sexual          sexual or explicit words; any sexual word with a child in the same line adds `minors`   block
    hate            slurs, threats of violence, a group told to die or leave, abuse words                  block
    claims          medical or money claims ("cures diabetes", "guaranteed returns")                        review

The lists are versioned (`VERSION`, written to every line check with the rule
ids): change a list, bump the version. A line is normalised first (NFKC, lower
case, zero-width characters and the dots in "O.T.P" taken out, a second copy
with 0/1/3/4/5/@/$ read as letters), and every pattern runs on both copies.
A credential ask said as a warning ("never share your OTP") is not a block.
Under 5 ms a line (tests/safety/test_line_checks.py measures it).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.safety.figures import LIST as FIGURES_LIST

VERSION = "rules-2026-10-31.2"

BLOCK_CATEGORIES = ("fraud", "impersonation", "political", "sexual", "hate")
REVIEW_CATEGORIES = ("claims",)

# A word edge that also knows Devanagari letters and their vowel signs (re's \b does not).
_L = r"(?<![\w\u0900-\u0963\u0966-\u097F])"   # the danda (U+0964, U+0965) ends a word
_R = r"(?![\w\u0900-\u0963\u0966-\u097F])"


def _alt(*words: str) -> str:
    return "(?:" + "|".join(sorted(words, key=len, reverse=True)) + ")"


def _w(*words: str) -> str:
    """Any of the words, as whole words."""
    return _L + _alt(*words) + _R


# ── fraud ────────────────────────────────────────────────────────────────────

_CREDENTIAL = _w(
    r"otp", r"otps", r"one[ -]?time[ -]?password", r"pin(?! ?codes?)(?!code)", r"m-?pin", r"upi pin", r"atm pin", r"cvv", r"cvc",
    r"password", r"passcode", r"card number", r"card no", r"card details", r"card ki details", r"debit card details",
    r"credit card details", r"card ke peeche ka number", r"bank details", r"bank account details", r"account number",
    r"account details", r"a/c number", r"net ?banking (?:password|id|details)", r"login details", r"verification code",
    r"security code", r"aadhaar number", r"aadhar number", r"pan number",
    r"ओटीपी", r"पिन(?! कोड)", r"यूपीआई पिन", r"एटीएम पिन", r"पासवर्ड", r"सीवीवी", r"कार्ड नंबर", r"कार्ड की जानकारी",
    r"कार्ड डिटेल्स", r"बैंक डिटेल्स", r"बैंक की जानकारी", r"खाता संख्या", r"खाता नंबर", r"अकाउंट नंबर", r"आधार नंबर",
)
# English asks come before what they ask for; Hindi and Hinglish asks come after it.
_ASK_BEFORE = _w(r"share", r"tell", r"send", r"give", r"enter", r"type", r"read out", r"confirm", r"provide",
                 r"forward", r"text", r"whatsapp", r"submit", r"verify", r"say", r"tell us", r"tell me",
                 r"बताएं", r"बताइए", r"बताओ", r"भेजें", r"भेजो", r"भेजिए", r"शेयर करें", r"दीजिए")
_ASK_AFTER = _w(r"batao", r"bataiye", r"batayein", r"bataen", r"bata do", r"bata dijiye", r"bata dena",
                r"bhejo", r"bhejiye", r"bhej do", r"bhej dijiye", r"share karo", r"share karein", r"share kijiye",
                r"share kar do", r"share kare", r"de do", r"dijiye", r"dena", r"daalo", r"daaliye", r"likho", r"bolo",
                r"boliye", r"confirm karo", r"confirm karein", r"send karo", r"send karein", r"do",
                r"बताएं", r"बताइए", r"बताओ", r"बता दें", r"बता दीजिए", r"भेजें", r"भेजो", r"भेजिए", r"भेज दें",
                r"शेयर करें", r"शेयर कीजिए", r"शेयर करो", r"दें", r"दीजिए", r"दो", r"डालें", r"बोलिए", r"बोलो", r"लिखें")
_NEAR = r"(?:\W+\S+){0,5}?\W+"
_NEGATION = re.compile(_w(r"never", r"don't", r"dont", r"do not", r"won't", r"will not", r"not", r"no one", r"nobody",
                          r"kabhi", r"kabhi bhi", r"mat", r"na karein", r"nahi", r"nahin", r"kisi ko nahi",
                          r"कभी", r"कभी भी", r"मत", r"नहीं", r"न करें", r"किसी को"))
_TRANSFER_NOW = [
    r"(?:transfer|send|move)\s+(?:the|this|that|all the|all your|your|all)\s+(?:money|amount|funds|payment|cash)"
    r"(?:\W+\S+){0,4}?\W+" + _alt(r"now", r"immediately", r"right now", r"right away", r"urgently", r"today itself", r"abhi"),
    _w(r"abhi", r"turant", r"jaldi", r"fauran") + r"\s+(?:\S+\s+){0,2}?(?:paise|paisa|rupaye|rupees|payment|amount|rakam)\s+"
    r"(?:\S+\s+){0,2}?(?:transfer|bhej|send)",
    r"(?:paise|paisa|rupaye|payment|amount|rakam)\s+" + _alt(r"abhi", r"turant", r"jaldi", r"fauran") + r"\s+(?:\S+\s+){0,2}?"
    r"(?:transfer|bhej|send)",
    _alt(r"अभी", r"तुरंत", r"फौरन", r"जल्दी") + r"\s+(?:\S+\s+){0,3}?(?:पैसे|पैसा|रुपये|रकम|पेमेंट)\s+(?:\S+\s+){0,3}?"
    r"(?:ट्रांसफर|भेज)",
    r"(?:पैसे|पैसा|रुपये|रकम|पेमेंट)\s+(?:\S+\s+){0,2}?" + _alt(r"अभी", r"तुरंत", r"फौरन") + r"\s+(?:\S+\s+){0,2}?(?:ट्रांसफर|भेज)",
]
_ACCOUNT_THREAT = [
    r"(?:account|card|sim|number|kyc|wallet)\s+(?:will be|is being|has been|gets)\s+(?:blocked|suspended|closed|deactivated|frozen)",
    r"(?:account|card|sim|khata|kyc)\s+(?:\S+\s+)?(?:block|band|suspend|freeze)\s+(?:ho jayega|ho jaega|ho jayegi|kar diya jayega)",
    r"(?:खाता|अकाउंट|कार्ड|सिम|केवाईसी)\s+(?:\S+\s+)?(?:बंद|ब्लॉक|फ्रीज)\s+(?:हो जाएगा|हो जायेगा|हो जाएगी|कर दिया जाएगा)",
]

# ── impersonation ────────────────────────────────────────────────────────────

_BODIES_EN = _alt(r"the police", r"police", r"cyber cell", r"cyber crime", r"cyber police", r"crime branch", r"cbi",
                  r"enforcement directorate", r"income tax department", r"income tax", r"customs", r"customs department",
                  r"rbi", r"reserve bank", r"reserve bank of india", r"sebi", r"trai", r"uidai", r"government of india",
                  r"the government of", r"ministry of", r"narcotics", r"narcotics bureau", r"interpol", r"fbi",
                  r"irs", r"sbi", r"state bank", r"hdfc", r"hdfc bank", r"icici", r"icici bank", r"axis bank", r"your bank",
                  r"bank manager", r"bank officer", r"bank official", r"electricity board", r"electricity department",
                  r"telecom department", r"department of telecom", r"amazon support", r"income tax office")
_IMPERSONATE = [
    _w(r"i am", r"i'm", r"im", r"this is", r"we are", r"we're", r"calling from", r"speaking from", r"calling on behalf of",
       r"on behalf of", r"message from", r"call from", r"officer from", r"official from")
    + r"\s+(?:a\s+|an\s+|the\s+|your\s+)?(?:senior\s+)?" + _BODIES_EN + _R,
    _w(r"i am", r"i'm", r"this is") + r"\s+(?:a\s+|an\s+|the\s+)?(?:senior\s+)?"
    + _alt(r"police officer", r"police inspector", r"inspector", r"cbi officer", r"ips officer", r"ias officer",
           r"tax officer", r"customs officer", r"government officer", r"government official", r"rbi officer", r"judge")
    + _R,
    _alt(r"police", r"rbi", r"bank", r"income tax", r"cyber cell", r"cbi", r"sarkar", r"sarkari daftar", r"customs",
         r"thana", r"court", r"bijli vibhag", r"sbi", r"hdfc", r"icici")
    + r"\s+(?:\S+\s+){0,2}?(?:se|ki taraf se)\s+(?:bol|baat kar)\s+(?:raha|rahi|rahe)",
    _w(r"main", r"mai", r"mein", r"hum") + r"\s+(?:\S+\s+){0,2}?"
    + _alt(r"police officer", r"inspector", r"police wala", r"daroga", r"cbi officer", r"bank manager", r"bank officer",
           r"tax officer", r"sarkari afsar", r"officer")
    + r"\s+(?:hoon|hun|hu|hain)" + _R,
    _alt(r"पुलिस", r"आरबीआई", r"रिज़र्व बैंक", r"रिजर्व बैंक", r"बैंक", r"आयकर विभाग", r"इनकम टैक्स", r"सीबीआई", r"साइबर सेल",
         r"सरकार", r"कस्टम", r"थाने", r"कोर्ट", r"बिजली विभाग")
    + r"\s+(?:\S+\s+){0,2}?(?:से|की ओर से|की तरफ से)\s+(?:बोल|बात कर)\s+(?:रहा|रही|रहे)",
    r"मैं\s+(?:\S+\s+){0,2}?" + _alt(r"पुलिस अधिकारी", r"इंस्पेक्टर", r"दरोगा", r"सीबीआई अधिकारी", r"बैंक मैनेजर", r"अधिकारी",
                                     r"टैक्स अधिकारी") + r"\s+(?:हूं|हूँ|हैं)",
]
_FIGURES_HI = ("नरेंद्र मोदी", "मोदी", "राहुल गांधी", "अमिताभ बच्चन", "शाहरुख खान", "शाहरुख़ ख़ान", "सलमान खान", "आमिर खान",
               "दीपिका पादुकोण", "प्रियंका चोपड़ा", "आलिया भट्ट", "विराट कोहली", "सचिन तेंदुलकर", "धोनी", "रजनीकांत",
               "मुकेश अंबानी", "रतन टाटा")


def _figures() -> list[str]:
    names = [ln.strip().lower() for ln in FIGURES_LIST.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    return names + ["modi", "modi ji", "pm modi"] + list(_FIGURES_HI)


def _named_person() -> list[str]:
    names = _alt(*[re.escape(n) for n in _figures()])
    return [
        _w(r"i am", r"i'm", r"im", r"this is", r"it's", r"its", r"main", r"mai", r"मैं", r"यह", r"ये") + r"\s+"
        + names + r"(?!'s)" + _R,
        _L + names + r"\s+" + _alt(r"here", r"speaking", r"bol raha hoon", r"bol rahi hoon", r"bol raha hu", r"bol rahi hu",
                                     r"baat kar raha hoon", r"बोल रहा हूं", r"बोल रही हूं", r"बोल रहा हूँ", r"बोल रही हूँ") + _R,
    ]


# ── political ────────────────────────────────────────────────────────────────

_PARTIES_ANY_CASE = _w(r"bjp", r"tmc", r"dmk", r"aiadmk", r"bsp", r"ncp", r"jdu", r"jd\(u\)", r"rjd", r"tdp", r"ysrcp",
                       r"brs", r"cpi", r"cpi\(m\)", r"cpm", r"shiv sena", r"samajwadi party", r"bahujan samaj party",
                       r"aam aadmi party", r"congress party", r"indian national congress", r"bharatiya janata party",
                       r"republican party", r"democratic party", r"labour party", r"conservative party", r"trinamool",
                       r"भाजपा", r"बीजेपी", r"कांग्रेस", r"आम आदमी पार्टी", r"समाजवादी पार्टी", r"बसपा", r"तृणमूल",
                       r"शिवसेना", r"आप पार्टी")
_PARTIES_CASED = re.compile(r"(?<![A-Za-z])(?:AAP|INC|SP|MNS)(?![A-Za-z])")       # "aap" (you) is everyday Hinglish
_CUES = (r"vote", r"votes", r"voting", r"party", r"parties", r"candidate", r"candidates", r"neta", r"leader", r"mla",
         r"mp", r"minister", r"government", r"sarkar", r"constituency", r"ballot", r"polling", r"bjp", r"congress",
         r"panja", r"panje", r"kamal", r"jhaadu", r"jitao", r"jitayein", r"harao", r"opposition", r"vipaksh",
         r"वोट", r"पार्टी", r"नेता", r"सरकार", r"उम्मीदवार", r"कमल", r"पंजा", r"झाड़ू", r"जिताएं", r"जिताओ", r"हराओ",
         r"हराएं", r"विपक्ष", r"भाजपा", r"कांग्रेस")
_ELECTION = _w(r"election", r"elections", r"by-election", r"bypoll", r"polling booth", r"polling booths", r"polling day",
               r"polling station", r"ballot", r"evm", r"evms", r"chunav", r"chunaav", r"matdaan", r"matdan", r"चुनाव",
               r"मतदान", r"उम्मीदवार", r"प्रत्याशी", r"वोटिंग", r"lok sabha", r"vidhan sabha", r"लोकसभा", r"विधानसभा",
               r"manifesto", r"घोषणापत्र")
_VOTE_ASK = (r"(?:vote|वोट)\s+(?:\S+\s+){0,2}?" + _alt(r"do", r"dein", r"karein", r"kare", r"karo", r"dena", r"dijiye",
                                                        r"daalo", r"dalein", r"दें", r"करें", r"डालें", r"दो", r"दीजिए",
                                                        r"डालो") + _R)


def _both(a: str, b: str) -> str:
    """Two things in one line, in either order (an election word with a political cue: "the election of the
    year: tea or coffee" and "vote for your flavour on the app" pass)."""
    return r"^(?=.*?" + a + r")(?=.*?" + b + r")"


_POLITICAL = [
    _both(_ELECTION, _w(*[c for c in _CUES if c not in ("polling", "ballot")], r"jitana", r"harana", r"हराना", r"जिताना",
                        r"dabana", r"दबाना", r"button", r"बटन")),
    _w(r"vote for", r"vote against", r"cast your vote", r"don't vote", r"do not vote", r"go and vote", r"go vote",
       r"voting for", r"vote him", r"vote her") + r"(?:\W+\S+){0,4}?\W+"
    + _alt(r"party", r"candidate", r"leader", r"neta", r"mla", r"mp", r"minister", r"government", r"sarkar", r"him", r"her",
           r"them", r"modi", r"gandhi", r"bjp", r"congress"),
    _both(_VOTE_ASK, _w(*[c for c in _CUES if c not in ("vote", "votes", "voting", "वोट")], r"chunav", r"election",
                        r"चुनाव", r"मतदान")),
    _w(r"prime minister", r"chief minister", r"mukhyamantri", r"pradhan mantri", r"प्रधानमंत्री", r"मुख्यमंत्री")
    + r"(?:\W+\S+){0,6}?\W+" + _alt(r"vote", r"support", r"elect", r"re-elect", r"resign", r"corrupt", r"chor", r"वोट",
                                    r"चोर", r"भ्रष्ट", r"jitao", r"jitayein", r"जिताएं", r"हराएं", r"harao"),
    _w(r"re-elect", r"reelect", r"don't let") + r"(?:\W+\S+){0,6}?\W+" + _alt(r"prime minister", r"chief minister", r"mla",
                                                                              r"mp", r"minister", r"party", r"government"),
]

# ── sexual, minors ───────────────────────────────────────────────────────────

_SEXUAL = _w(r"porn", r"porno", r"pornographic", r"pornography", r"xxx", r"sex", r"sexual", r"sexually", r"intercourse",
             r"orgasm", r"horny", r"blowjob", r"blow job", r"handjob", r"boobs", r"tits", r"dick", r"cock", r"pussy",
             r"cum", r"erotic", r"fetish", r"onlyfans", r"strip club", r"escort service", r"nudes", r"send nudes",
             r"chudai", r"chodna", r"nangi", r"nanga", r"lund", r"sexy video", r"blue film",
             r"सेक्स", r"सेक्सी वीडियो", r"नंगी", r"नंगा", r"अश्लील", r"चुदाई", r"संभोग", r"पोर्न", r"लंड", r"चूत", r"ब्लू फिल्म")
_MINORS = _w(r"child", r"children", r"kid", r"kids", r"minor", r"minors", r"underage", r"under-age", r"teen", r"teens",
             r"teenage", r"teenager", r"schoolgirl", r"schoolboy", r"school girl", r"school boy", r"little girl",
             r"little boy", r"(?:[1-9]|1[0-7])[ -]?(?:year|yr)s?[ -]?old", r"bachcha", r"bachchi", r"bacche", r"bachche",
             r"bachi", r"nabalig", r"choti ladki", r"chhoti ladki", r"बच्चा", r"बच्ची", r"बच्चे", r"बच्चों", r"नाबालिग",
             r"छोटी लड़की", r"स्कूल की लड़की")

# ── hate, threats, harassment ────────────────────────────────────────────────

_SLURS = _w(r"nigger", r"niggers", r"nigga", r"faggot", r"faggots", r"fag", r"kike", r"chink", r"chinks", r"spic",
            r"tranny", r"paki", r"pakis", r"retard", r"retards", r"katua", r"katuwe", r"mulla", r"mulle", r"chamar",
            r"bhangi", r"chuhra", r"bitch", r"whore", r"slut", r"randi", r"kutiya", r"harami", r"haramzada",
            r"haramzade", r"madarchod", r"behenchod", r"bhenchod", r"chutiya", r"chutiye", r"gaandu", r"bhosdike",
            r"कटुआ", r"मुल्ला", r"चमार", r"भंगी", r"चूहड़ा", r"रंडी", r"कुतिया", r"हरामी", r"हरामज़ादा", r"हरामजादा",
            r"मादरचोद", r"बहनचोद", r"चूतिया", r"गांडू", r"भोसड़ीके")
_THREATS = [
    _w(r"i will", r"i'll", r"we will", r"we'll", r"gonna", r"going to") + r"\s+(?:\S+\s+){0,2}?"
    + _alt(r"kill", r"murder", r"shoot", r"stab", r"burn", r"rape", r"hurt") + r"\s+"
    + _alt(r"you", r"him", r"her", r"them", r"your family", r"your kids", r"your children") + _R,
    _w(r"kill", r"murder", r"shoot", r"stab", r"rape", r"lynch", r"hang") + r"\s+" + _alt(r"you", r"him", r"her", r"all of them",
                                                                                        r"those people") + _R,
    _w(r"you will die", r"you'll die", r"you are dead", r"you're dead", r"we know where you live", r"blow you up",
       r"bomb the", r"bomb your"),
    _w(r"jaan se maar", r"jaan se maarunga", r"maar dalunga", r"maar daalunga", r"maar dalenge", r"maar daalenge",
       r"maar dunga", r"maar doonga", r"maar denge", r"khatam kar dunga", r"khatam kar denge", r"zinda jala",
       r"ghar jala denge", r"tujhe dekh lunga", r"जान से मार", r"मार डालूंगा", r"मार डालूँगा", r"मार डालेंगे",
       r"मार दूंगा", r"मार देंगे", r"खत्म कर दूंगा", r"खत्म कर देंगे", r"ज़िंदा जला", r"जिंदा जला", r"तुझे देख लूंगा"),
]
_GROUPS = _alt(r"muslims?", r"hindus?", r"christians?", r"sikhs?", r"dalits?", r"jews?", r"gays?", r"immigrants?",
               r"biharis?", r"madrasis?", r"north indians?", r"south indians?", r"women", r"blacks", r"refugees",
               r"मुसलमान", r"मुसलमानों", r"हिंदू", r"हिंदुओं", r"ईसाई", r"सिख", r"दलित", r"बिहारी", r"औरतें")
_GROUP_HATE = [
    _L + _GROUPS + r"(?:\W+\S+){0,3}?\W+" + _alt(r"should die", r"must die", r"should be killed", r"deserve to die",
                                                  r"should be thrown out", r"should leave", r"go back", r"are dogs",
                                                  r"are vermin", r"are rats", r"are animals", r"are terrorists",
                                                  r"are filth", r"are a disease", r"ko maaro", r"ko bhagao", r"ko nikalo",
                                                  r"ko khatam karo", r"को मारो", r"को भगाओ", r"को निकालो", r"को खत्म करो"),
]

# ── claims (review) ──────────────────────────────────────────────────────────

_CLAIMS = [
    _w(r"cure", r"cures", r"cured", r"curing", r"reverse", r"reverses", r"heal", r"heals", r"eliminate", r"eliminates")
    + r"(?:\W+\S+){0,3}?\W+" + _alt(r"diabetes", r"cancer", r"covid", r"bp", r"blood pressure", r"hiv", r"aids",
                                    r"asthma", r"arthritis", r"thyroid", r"obesity", r"disease", r"diseases",
                                    r"infertility", r"kidney", r"heart disease", r"depression", r"autism", r"psoriasis"),
    _w(r"guaranteed", r"guarantee", r"guaranteed high", r"assured", r"pakka") + r"(?:\W+\S+){0,2}?\W+"
    + _alt(r"returns?", r"profits?", r"income", r"earnings", r"weight loss", r"cure", r"munafa", r"kamai"),
    r"(?:100|hundred)\s?(?:%|percent|per cent|pratishat|प्रतिशत)\s*(?:\S+\s+){0,1}?"
    + _alt(r"guaranteed", r"cure", r"returns?", r"safe returns", r"profit", r"इलाज", r"गारंटी", r"ilaaj", r"guarantee"),
    _w(r"double your money", r"triple your money", r"money doubles", r"risk[- ]free returns?", r"risk[- ]free investment",
       r"risk[- ]free profit", r"no risk returns?", r"no side effects", r"zero side effects", r"clinically proven to cure",
       r"paisa double", r"paise double", r"paisa dugna", r"paise dugne", r"guaranteed return", r"jad se khatam",
       r"jad se khatm", r"पैसा डबल", r"पैसे डबल", r"पैसा दोगुना", r"पैसे दोगुने", r"गारंटीड रिटर्न", r"गारंटीड मुनाफा",
       r"रिटर्न की गारंटी", r"मुनाफे की गारंटी", r"जड़ से खत्म", r"जड़ से ख़त्म", r"कोई साइड इफेक्ट नहीं"),
    r"lose\s+\d+\s?(?:kg|kgs|kilos?|pounds|lbs)\s+in\s+\d+\s+(?:days?|weeks?)",
    r"\d+\s?(?:kg|kilo)\s+(?:wazan\s+)?(?:kam|ghatayein|ghataiye)\s+(?:\S+\s+){0,2}?\d+\s+din",
    _alt(r"diabetes", r"sugar", r"cancer", r"bp", r"thyroid", r"motapa") + r"\s+(?:\S+\s+){0,2}?"
    + _alt(r"khatam", r"khatm", r"gayab", r"jad se", r"hamesha ke liye theek", r"puri tarah theek"),
    _alt(r"डायबिटीज", r"शुगर", r"मधुमेह", r"कैंसर", r"बीपी", r"थायराइड", r"मोटापा") + r"\s+(?:\S+\s+){0,3}?"
    + _alt(r"खत्म", r"ख़त्म", r"जड़ से", r"गायब", r"हमेशा के लिए ठीक", r"पूरी तरह ठीक"),
]


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    pattern: re.Pattern


def _compile(rule_id: str, category: str, *patterns: str, flags: int = re.IGNORECASE) -> list[Rule]:
    return [Rule(f"{rule_id}.{n}" if len(patterns) > 1 else rule_id, category, re.compile(p, flags))
            for n, p in enumerate(patterns, 1)]


def _rules() -> list[Rule]:
    out: list[Rule] = []
    out += _compile("fraud.ask", "fraud", _ASK_BEFORE + _NEAR + _CREDENTIAL, _CREDENTIAL + _NEAR + _ASK_AFTER)
    out += _compile("fraud.transfer_now", "fraud", *_TRANSFER_NOW)
    out += _compile("fraud.account_threat", "fraud", *_ACCOUNT_THREAT)
    out += _compile("impersonation.body", "impersonation", *_IMPERSONATE)
    out += _compile("impersonation.person", "impersonation", *_named_person())
    out += _compile("political.party", "political", _PARTIES_ANY_CASE)
    out.append(Rule("political.party_cased", "political", _PARTIES_CASED))
    out += _compile("political.election", "political", *_POLITICAL)
    out += _compile("sexual.words", "sexual", _SEXUAL)
    out += _compile("hate.slur", "hate", _SLURS)
    out += _compile("hate.threat", "hate", *_THREATS)
    out += _compile("hate.group", "hate", *_GROUP_HATE)
    out += _compile("claims", "claims", *_CLAIMS)
    return out


RULES = _rules()
_MINORS_RE = re.compile(_MINORS, re.IGNORECASE)
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_DOTTED = re.compile(r"(?<![a-z])((?:[a-z]\.){2,}[a-z]?)(?![a-z])")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s", "!": "i", "*": ""})


def normalise(text: str) -> tuple[str, ...]:
    """The line as the rules read it: one copy, and a second with look-alike digits read as letters."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t).replace("\u2019", "'").replace("\u2018", "'").lower()
    t = _DOTTED.sub(lambda m: m.group(1).replace(".", ""), t)
    t = " ".join(t.split())
    leet = t.translate(_LEET)
    return (t,) if leet == t else (t, leet)


@dataclass(frozen=True)
class RuleResult:
    verdict: str                      # pass | block | review
    categories: tuple[str, ...] = ()
    hits: tuple[str, ...] = ()

    @property
    def minors(self) -> bool:
        return "minors" in self.categories


def _negated(text: str, start: int, end: int) -> bool:
    """A credential ask said as a warning: a negation in the 40 characters before it, or in it."""
    return bool(_NEGATION.search(text[max(0, start - 40):end]))


def check(text: str) -> RuleResult:
    """Every rule over the line; block wins over review."""
    copies = normalise(text)
    raw = unicodedata.normalize("NFKC", text or "")
    hits: list[Rule] = []
    for rule in RULES:
        targets = (raw,) if rule.id == "political.party_cased" else copies
        for t in targets:
            m = rule.pattern.search(t)
            if m is None:
                continue
            if rule.category == "fraud" and rule.id.startswith("fraud.ask") and _negated(t, m.start(), m.end()):
                continue
            hits.append(rule)
            break
    if not hits:
        return RuleResult("pass")
    cats = list(dict.fromkeys(r.category for r in hits))
    if "sexual" in cats and any(_MINORS_RE.search(t) for t in copies):
        cats.insert(cats.index("sexual") + 1, "minors")
    blocking = [c for c in cats if c in BLOCK_CATEGORIES or c == "minors"]
    verdict = "block" if blocking else "review"
    ordered = blocking + [c for c in cats if c not in blocking] if blocking else cats
    return RuleResult(verdict, tuple(ordered), tuple(f"{r.id}@{VERSION}" for r in hits))
