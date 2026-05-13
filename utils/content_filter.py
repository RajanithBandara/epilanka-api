"""
3-Layer Content Filtering Pipeline for EpiLanka User Reports
============================================================

Layer 1 — Regex Link & Phrase Detection          (< 1ms,  sync)
Layer 2 — Spam / Profanity Keyword Detection     (< 5ms,  sync)
Layer 3 — Groq LLM: Health Validity + Toxicity  (500-1500ms, async)

Architecture change (Option B):
  Layers 3 (Detoxify toxic-bert) and 4 (Groq health relevance) have been
  MERGED into a single Groq call.  The LLM now simultaneously checks:
    • Is the text a genuine health report?      (was Layer 4)
    • Does it contain toxicity / threats / hate? (was Layer 3 / Detoxify)
  This gives llama-3.3-70b-quality judgement on BOTH dimensions in ONE
  API round-trip (~500-1500 ms) with ZERO RAM overhead — far better than
  running toxic-bert locally (which needed ~440 MB just for model weights).

  Fast-path shortcut: if the text contains clear health keywords AND passes
  the keyword toxicity pre-screen, we skip Groq entirely (< 8ms total).

Layer 3 fails silently (log + skip) on API errors so a Groq outage never
blocks a legitimate user report.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Regex Link & Suspicious Phrase Detection
# ══════════════════════════════════════════════════════════════════════════════

_LINK_PATTERNS: list[str] = [
    # Hard URLs
    r"https?://",
    r"ftp://",
    r"www\.",
    r"mailto:",
    # Bare domain-like patterns  (.com, .net, .lk, .org, .io, .gov, .edu, …)
    r"\b\w{2,}\.(?:com|net|org|io|lk|gov|edu|info|biz|co|app|me|tv|uk|au)\b",
    # URL shorteners
    r"\bbit\.ly\b|\btinyurl\b|\bt\.co\b|\bgoo\.gl\b|\bshort\.io\b",
    # Suspicious call-to-action phrases
    r"\bfollow\s+(?:this\s+)?link\b",
    r"\bclick\s+here\b",
    r"\bget\s+here\b",
    r"\bvisit\s+(?:this\s+)?(?:site|page|url|link|website)\b",
    r"\bcheck\s+(?:this\s+)?out\b",
    r"\bmy\s+(?:profile|page|website|data|info|details)\b",
    r"\bshare\s+(?:your|my)\s+(?:data|info|details|link)\b",
    r"\bsend\s+(?:your|my)\s+(?:data|info|details)\b",
    r"\bget\s+(?:your|my)\s+(?:data|info|details)\b",
    r"\bdownload\s+(?:now|here|this)\b",
    r"\bjoin\s+(?:now|here|us)\b",
    r"\bregister\s+(?:now|here)\b",
    r"\bsign\s+up\s+(?:now|here)\b",
]

_LINK_RE = re.compile("|".join(_LINK_PATTERNS), re.IGNORECASE)


def check_links(text: str) -> None:
    """Layer 1 — block any URLs, link-like patterns, or call-to-action phrases."""
    m = _LINK_RE.search(text)
    if m:
        raise ValueError(
            "Reports cannot contain links, URLs, or promotional phrases "
            f'(found: "{m.group().strip()}"). '
            "Please describe the health incident in plain text."
        )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Spam / Profanity Keyword Detection
# ══════════════════════════════════════════════════════════════════════════════

# Domain-specific extras loaded on top of the better-profanity dataset
_EXTRA_SPAM_WORDS: list[str] = [
    # Marketing / spam
    "buy now", "free offer", "limited time offer", "act now",
    "make money", "earn cash", "work from home", "weight loss",
    "casino", "lottery", "jackpot", "winner", "prize", "cash prize",
    "discount", "subscribe", "unsubscribe", "free trial", "risk free",
    "100% free", "guaranteed", "no cost", "earn money",
    # Personal data solicitation
    "send me your", "give me your", "share your details", "share your data",
    "personal information", "your password", "your email",
    "credit card", "bank account", "wire transfer", "western union",
    # Test / gibberish
    "asdf", "qwerty", "zxcv", "test123", "hello world",
    # Violence / threats not in profanity lists
    "bomb", "terrorist", "massacre", "genocide",
    # Public humiliation
    "public shame", "expose you", "expose him", "expose her",
    "name and shame", "humiliate",
    # Common profanity terms
    "shit", "fucking", "fuck", "fucked", "bitch", "asshole",
]

try:
    from better_profanity import profanity as _prof

    _prof.load_censor_words()
    _prof.add_censor_words(_EXTRA_SPAM_WORDS)
    _USE_BP = True
    logger.info("[ContentFilter] better-profanity dataset loaded.")
except ImportError:
    _USE_BP = False
    _FALLBACK_RE = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in _EXTRA_SPAM_WORDS) + r")\b",
        re.IGNORECASE,
    )
    logger.warning("[ContentFilter] better-profanity not available; using fallback list.")

# Additional hard-coded patterns for structural spam
_SPAM_STRUCT_PATTERNS = re.compile(
    r"(.)\1{6,}"          # 7+ repeated chars: "aaaaaaa"
    r"|[^\w\s]{5,}",      # 5+ consecutive special chars
    re.IGNORECASE,
)


def check_keywords(text: str) -> None:
    """Layer 2 — block profanity, spam keywords, and structural spam."""

    # Length guards
    if len(text) < 20:
        raise ValueError(
            "Report is too short. Please provide at least 20 characters "
            "describing the health incident."
        )
    if len(text) > 2000:
        raise ValueError(
            "Report exceeds the maximum length of 2,000 characters. "
            "Please shorten your description."
        )

    # Profanity / spam keyword check
    if _USE_BP:
        if _prof.contains_profanity(text):
            raise ValueError(
                "Your report contains inappropriate language or spam phrases. "
                "Please keep submissions related to health incidents only."
            )
    else:
        if _FALLBACK_RE.search(text):
            raise ValueError(
                "Your report contains inappropriate or spam content. "
                "Please keep submissions related to health incidents only."
            )

    # Structural spam
    if _SPAM_STRUCT_PATTERNS.search(text):
        raise ValueError(
            "Your report appears to contain spam (repeated characters or symbols). "
            "Please describe a real health incident."
        )

    # All-caps check (>75% uppercase for texts with 30+ letters)
    letters = re.findall(r"[a-zA-Z]", text)
    if len(letters) > 30:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio > 0.75:
            raise ValueError(
                "Please avoid writing in ALL CAPS. "
                "Use normal sentence case for your health report."
            )

    # Low word variety — copy-paste spam
    words = re.findall(r"\w+", text.lower())
    if len(words) >= 10:
        if (len(set(words)) / len(words)) < 0.3:
            raise ValueError(
                "Your report contains too much repeated text. "
                "Please describe the health incident in your own words."
            )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Groq LLM: Combined Health Validity + Toxicity Check
#
# A single llama-3.3-70b call replaces both:
#   • the former Detoxify toxic-bert (Layer 3) — 440 MB RAM, not viable on 1 GB
#   • the former Groq health-relevance call  (Layer 4) — was a separate request
#
# The model returns exactly one token: VALID | TOXIC | IRRELEVANT
#
# Fast-path shortcuts skip the Groq call when the answer is obviously safe:
#   • Text contains a recognised health keyword  AND
#   • Text does NOT contain an obvious toxicity signal
# ══════════════════════════════════════════════════════════════════════════════

# Clear health-related keywords — if ANY of these appear the text is almost
# certainly a genuine health report.  We still run the toxicity half of the
# prompt unless a hard toxicity signal is also absent.
_HEALTH_SHORTCUTS: frozenset[str] = frozenset({
    "fever", "cough", "dengue", "malaria", "cholera", "diarrhea", "diarrhoea",
    "vomiting", "nausea", "symptom", "symptoms", "disease", "infection",
    "infected", "patient", "patients", "cases", "hospital", "clinic",
    "outbreak", "typhoid", "leptospirosis", "hepatitis", "tuberculosis",
    "measles", "chickenpox", "flu", "influenza", "respiratory", "illness",
    "sick", "sickness", "pneumonia", "covid", "virus", "bacterial", "parasitic",
    "treatment", "diagnosed", "diagnosis", "death", "mortality", "epidemic",
    "pandemic", "health incident", "health issue", "medical", "doctor", "nurse",
    "ward", "icu", "quarantine", "isolation", "rash", "headache", "fatigue",
    "abdominal", "dizziness", "bleeding", "wound", "injury", "fracture",
    "poisoning", "allergy", "inflammation", "swelling", "disability",
})

# Hard toxicity signals that mean the shortcut should NOT apply even if a
# health keyword is present (e.g. "I will kill all fever patients").
_HARD_TOXICITY_SIGNALS: list[str] = [
    "i will kill", "i'll kill", "going to kill", "gonna kill",
    "i will hurt", "i'll hurt", "i will attack", "you will die",
    "i will rape", "kill yourself", "kys", "end your life",
    "i'll find you", "i know where you live",
    "fuck you", "go fuck yourself",
    "nigger", "nigga", "faggot", "chink", "kike", "spic",
]
_HARD_TOXICITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _HARD_TOXICITY_SIGNALS) + r")\b",
    re.IGNORECASE,
)

# The merged prompt — asks the model to decide health validity AND toxicity in
# one shot and respond with exactly one word.
_GROQ_COMBINED_PROMPT = """\
You are a content moderator for EpiLanka, Sri Lanka's official disease surveillance platform.

Analyse the REPORT TEXT below and respond with EXACTLY ONE of these three words — nothing else:

  VALID       — The text is a genuine health or disease incident report AND contains
                no harmful, toxic, threatening, or hateful content.

  TOXIC       — The text contains threats, hate speech, severe insults, identity attacks,
                or sexual harassment — regardless of whether it mentions health topics.

  IRRELEVANT  — The text is not a genuine health report (spam, ads, gibberish, personal
                grievances, test entries, social media opinion, etc.) but is NOT toxic.

Rules for VALID:
  • Must describe real disease symptoms, affected people, a specific disease/illness,
    a health outbreak, or treatment sought.
  • Must be written in a factual, respectful tone.

Rules for TOXIC (takes priority over VALID):
  • Any direct threat ("I will kill/hurt/attack …")
  • Hate speech or slurs targeting race, religion, ethnicity, gender, or sexuality
  • Sexual harassment or explicit content
  • Calls for self-harm

Rules for IRRELEVANT:
  • Spam, promotions, marketing, advertisements
  • Random or gibberish text
  • Personal grievances unrelated to disease or public health
  • Social commentary with no health incident described

REPORT TEXT:
"{text}"

Your answer (one word only):"""

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


async def check_with_groq(text: str) -> None:
    """
    Layer 3 — Single Groq call that simultaneously checks health validity
    and toxicity.  Returns one of: VALID | TOXIC | IRRELEVANT.

    Fast-path: skip Groq entirely when the text clearly contains a recognised
    health keyword AND no hard toxicity signal is present.
    """
    words_in_text = set(re.findall(r"\b\w+\b", text.lower()))
    has_health_keyword = bool(words_in_text & _HEALTH_SHORTCUTS)
    has_hard_toxicity  = bool(_HARD_TOXICITY_RE.search(text))

    if has_health_keyword and not has_hard_toxicity:
        logger.debug(
            "[ContentFilter] Fast-path: health keyword present, no hard toxicity — skipping Groq."
        )
        return

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.warning("[ContentFilter] GROQ_API_KEY not set — skipping Layer 3.")
        return

    prompt = _GROQ_COMBINED_PROMPT.format(text=text[:800])  # cap to keep costs low

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                _GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 5,   # VALID / TOXIC / IRRELEVANT + margin
                },
            )

        if resp.status_code != 200:
            logger.warning(
                f"[ContentFilter] Groq returned {resp.status_code} — skipping Layer 3."
            )
            return

        data   = resp.json()
        answer: str = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "VALID")
            .strip()
            .upper()
        )

        logger.info(f"[ContentFilter] Groq combined classifier → {answer}")

        if answer.startswith("TOXIC"):
            raise ValueError(
                "Your report contains harmful, threatening, or offensive content. "
                "Please keep your submission factual, respectful, and health-related."
            )

        if answer.startswith("IRRELEVANT"):
            raise ValueError(
                "Your report doesn't appear to describe a real health or disease incident. "
                "EpiLanka only accepts genuine health reports such as disease outbreaks, "
                "symptoms, or patient cases. Please describe the actual health situation."
            )

        # VALID — allow through
        logger.debug("[ContentFilter] Groq: report accepted as VALID.")

    except ValueError:
        raise
    except Exception as e:
        # A Groq outage / network error must never block a legitimate report.
        logger.warning(f"[ContentFilter] Groq combined check error (skipping): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE — run all 3 layers in order
# ══════════════════════════════════════════════════════════════════════════════

async def run_content_filter_pipeline(description: str) -> None:
    """
    Run the full 3-layer content filter pipeline.

    Raises ValueError with a user-facing message on the FIRST failed layer.
    Layer 3 is skipped silently on Groq API errors.

    Order (fastest → slowest):
        Layer 1 → Regex link/phrase detection          (< 1ms)
        Layer 2 → Spam & profanity keyword detection   (< 5ms)
        Layer 3 → Groq LLM: health validity + toxicity (500-1500ms or skipped)
    """
    text = description.strip()

    # Layer 1 — instant regex
    check_links(text)

    # Layer 2 — keyword/profanity + structural spam
    check_keywords(text)

    # Layer 3 — Groq: combined health-validity + toxicity (async)
    await check_with_groq(text)
