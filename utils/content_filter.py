"""
4-Layer Content Filtering Pipeline for EpiLanka User Reports
============================================================

Layer 1 — Regex Link & Phrase Detection        (< 1ms, sync)
Layer 2 — Spam/Profanity Keyword Detection     (< 5ms, sync)
Layer 3 — Detoxify ML Toxicity Detection       (50-200ms, sync, server-only)
Layer 4 — Groq Health Relevance Classifier     (500-1500ms, async, server-only)

Each layer raises ValueError with a user-friendly message on failure.
Layers 3-4 fail silently (log + skip) on model/API errors so the
API never crashes due to filter unavailability.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

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

_LINK_RE = re.compile("|".join(_LINK_PATTERNS))


def check_links(text: str) -> None:
    """Layer 1 — block any URLs, link-like patterns, or call-to-action phrases."""
    m = _LINK_RE.search(text.casefold())
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
    # Common profanity terms used by tests and production reports
    "shit", "fucking", "fuck", "fucked", "bitch", "asshole",
]

_prof: Any = None

try:
    from better_profanity import profanity as _better_profanity

    _better_profanity.load_censor_words()
    _better_profanity.add_censor_words(_EXTRA_SPAM_WORDS)
    _prof = _better_profanity
    _USE_BP = True
    logger.info("[ContentFilter] better-profanity dataset loaded.")
except ImportError:
    _prof = None
    _better_profanity = None
    _USE_BP = False
    _FALLBACK_RE = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in _EXTRA_SPAM_WORDS) + r")\b",
    )
    logger.warning("[ContentFilter] better-profanity not available; using fallback list.")

_EXTRA_SPAM_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _EXTRA_SPAM_WORDS) + r")\b",
)

# Additional hard-coded patterns for structural spam
_SPAM_STRUCT_PATTERNS = re.compile(
    r"(.)\1{6,}"          # 7+ repeated chars: "aaaaaaa"
    r"|[^\w\s]{5,}",      # 5+ consecutive special chars
    re.IGNORECASE,
)


def check_keywords(text: str) -> None:
    """Layer 2 — block profanity, spam keywords, and structural spam."""

    # Length guards
    text_len = len(text)
    if text_len < 20:
        raise ValueError(
            "Report is too short. Please provide at least 20 characters "
            "describing the health incident."
        )
    if text_len > 2000:
        raise ValueError(
            "Report exceeds the maximum length of 2,000 characters. "
            "Please shorten your description."
        )

    text_cf = text.casefold()

    # Fast pre-scan for the most common spam/promotional phrases.
    # This catches obvious abuse before calling the heavier profanity engine.
    if _EXTRA_SPAM_RE.search(text_cf):
        raise ValueError(
            "Your report contains inappropriate or spam content. "
            "Please keep submissions related to health incidents only."
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
    words = re.findall(r"\w+", text_cf)
    if len(words) >= 10:
        if (len(set(words)) / len(words)) < 0.3:
            raise ValueError(
                "Your report contains too much repeated text. "
                "Please describe the health incident in your own words."
            )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Detoxify ML Toxicity Detection
# ══════════════════════════════════════════════════════════════════════════════

_detoxify_model = None
_detoxify_attempted = False


def _get_detoxify():
    """Lazy-load the Detoxify model once. Returns None if unavailable."""
    global _detoxify_model, _detoxify_attempted
    if _detoxify_attempted:
        return _detoxify_model
    _detoxify_attempted = True
    try:
        from detoxify import Detoxify
        _detoxify_model = Detoxify("original")
        logger.info("[ContentFilter] Detoxify model loaded.")
    except Exception as e:
        logger.warning(f"[ContentFilter] Detoxify not available: {e}")
    return _detoxify_model


# Thresholds — tuned conservatively to avoid false positives in health contexts
_TOXICITY_THRESHOLDS: dict[str, float] = {
    "toxicity":        0.70,
    "severe_toxicity": 0.60,
    "insult":          0.65,
    "threat":          0.70,
    "identity_attack": 0.65,
    "obscene":         0.70,
}


def check_toxicity(text: str) -> None:
    """Layer 3 — ML-based toxicity detection via Detoxify (toxic-bert)."""
    model = _get_detoxify()
    if model is None:
        return  # Skip gracefully if model unavailable

    try:
        scores: dict[str, float] = model.predict(text)
        for label, threshold in _TOXICITY_THRESHOLDS.items():
            score = float(scores.get(label, 0.0))
            if score > threshold:
                logger.info(
                    f"[ContentFilter] Toxicity blocked — {label}={score:.2f} "
                    f"(threshold={threshold})"
                )
                raise ValueError(
                    "Your report contains harmful, threatening, or offensive content. "
                    "Please keep your submission factual, respectful, and health-related."
                )
    except ValueError:
        raise
    except Exception as e:
        # Model inference errors should never block a legitimate report
        logger.warning(f"[ContentFilter] Detoxify inference error (skipping): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — Groq Health Relevance AI Classifier
# ══════════════════════════════════════════════════════════════════════════════

# If the text contains ANY of these keywords it is almost certainly
# health-related — skip the expensive Groq call for speed.
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

_GROQ_CLASSIFIER_PROMPT = """\
You are a health report validator for EpiLanka, Sri Lanka's disease surveillance platform.

TASK: Determine if the text below is a genuine health or disease incident report.

A VALID report MUST describe one or more of:
- Real disease symptoms experienced by people
- Number of affected people or patients
- A specific disease, illness, or health condition
- A health outbreak or community health concern
- Treatment sought or medical response

INVALID reports include:
- Spam, promotions, advertisements, or marketing content
- Personal data requests or solicitations
- Links, URLs, or calls to action
- Social media opinions or general commentary
- Random/gibberish text or test entries
- Personal grievances unrelated to disease/health
- Public humiliation or threats

REPORT TEXT:
"{text}"

Respond with ONLY one word: YES if valid health report, NO if not."""

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


async def check_health_relevance(text: str) -> None:
    """Layer 4 — Groq LLM classifier to verify health relevance."""

    # Fast path: if the text clearly mentions health-related terms, skip Groq
    words_in_text = set(re.findall(r"\b\w+\b", text.lower()))
    if words_in_text & _HEALTH_SHORTCUTS:
        logger.debug("[ContentFilter] Health shortcut matched — skipping Groq.")
        return

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.warning("[ContentFilter] GROQ_API_KEY not set — skipping Layer 4.")
        return

    prompt = _GROQ_CLASSIFIER_PROMPT.format(text=text[:800])  # cap prompt length

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
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
                    "max_tokens": 5,
                },
            )

        if resp.status_code != 200:
            logger.warning(
                f"[ContentFilter] Groq returned {resp.status_code} — skipping Layer 4."
            )
            return

        data = resp.json()
        answer: str = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "YES")
            .strip()
            .upper()
        )

        logger.info(f"[ContentFilter] Groq health classifier → {answer}")

        if answer.startswith("NO"):
            raise ValueError(
                "Your report doesn't appear to describe a real health or disease incident. "
                "EpiLanka only accepts genuine health reports such as disease outbreaks, "
                "symptoms, or patient cases. Please describe the actual health situation."
            )

    except ValueError:
        raise
    except Exception as e:
        # Never block a report just because the AI check failed
        logger.warning(f"[ContentFilter] Groq health check error (skipping): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE — run all 4 layers in order
# ══════════════════════════════════════════════════════════════════════════════

async def run_content_filter_pipeline(description: str) -> None:
    """
    Run the full 4-layer content filter pipeline.

    Raises ValueError with a user-facing message on the FIRST failed layer.
    Layers 3-4 are skipped silently on model/API errors.

    Order (fastest → slowest):
        Layer 1 → Regex link/phrase detection
        Layer 2 → Spam & profanity keyword detection
        Layer 3 → Detoxify ML toxicity scoring
        Layer 4 → Groq health relevance classification
    """
    text = description.strip()

    # Layer 1 — instant regex
    check_links(text)

    # Layer 2 — keyword/profanity + structural spam
    check_keywords(text)

    # Layer 3 — ML toxicity (sync, 50-200ms)
    check_toxicity(text)

    # Layer 4 — AI health relevance (async, 500-1500ms or skipped)
    await check_health_relevance(text)
