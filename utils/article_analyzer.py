"""
Article analyzer — Groq + Redis cache-aside.

Public articles are managed by health officers as plain title/summary/body text.
For the user dashboard we want the body broken down into a user-friendly,
structured form (TL;DR, key points, sections, do/don't, when to seek help, etc.).

On the first fetch for an article we call Groq once, store the structured
result in Redis, and serve subsequent requests straight from cache. The cache
key embeds the article's `updatedAt` so officer edits naturally produce a new
key; the article controller also explicitly invalidates on update/delete.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from utils.redis_client import cache_delete_pattern, cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

ANALYSIS_VERSION = "v1"
_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days; officer edits invalidate explicitly
_GROQ_TIMEOUT_SECONDS = 25.0
_MAX_BODY_CHARS = 8000  # keep the prompt well within Groq context limits


# ── Cache key helpers ─────────────────────────────────────────────────────────


def _cache_key(article_id: str, updated_at: str | None) -> str:
    return f"article:analysis:{ANALYSIS_VERSION}:{article_id}:{updated_at or 'na'}"


def _cache_pattern(article_id: str) -> str:
    return f"article:analysis:{ANALYSIS_VERSION}:{article_id}:*"


# ── Groq prompt ───────────────────────────────────────────────────────────────


_SYSTEM_PROMPT = """\
You are a public-health editor for EpiLanka, Sri Lanka's disease surveillance
platform. You rewrite officer-authored articles into a clear, structured,
reader-friendly form for ordinary people. Use plain English at a Grade 8
reading level. Never invent medical facts or numbers that are not in the
source. If something is missing in the source, leave that array empty
rather than fabricating content.

You MUST respond with a single valid JSON object that matches this schema
exactly (no commentary, no markdown fences):

{
  "tldr": string,                    // 2-3 sentence plain-English summary
  "readingTimeMinutes": number,      // estimated reading time, integer >= 1
  "keyPoints": string[],             // 3-6 short bullet points, no markdown
  "sections": [                      // 2-5 logical sections
    { "heading": string, "body": string }
  ],
  "doAndDont": {
    "do":   string[],                // 0-5 practical actions
    "dont": string[]                 // 0-5 things to avoid
  },
  "whenToSeekHelp": string[],        // 0-5 warning signs that warrant a clinic/doctor
  "relatedDiseases": string[],       // canonical disease names mentioned in the article
  "audience": "general" | "parents" | "officers" | "clinicians",
  "tone": "informative" | "urgent" | "preventive" | "reassuring"
}

Rules:
- Keep every string concise and free of markdown symbols (*, #, etc.).
- Do not include URLs, phone numbers, or invented sources.
- The "sections" bodies should be 2-5 sentences each, in plain prose.
- If the article does not contain any do/don't or warning-sign material,
  return empty arrays. Do not guess.
"""


def _build_user_prompt(article: dict) -> str:
    title = (article.get("title") or "").strip()
    summary = (article.get("summary") or "").strip()
    body = (article.get("body") or "").strip()
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n[truncated]"
    category = (article.get("category") or "general").strip()
    tags = article.get("tags") or []
    tag_list = ", ".join(t for t in tags if isinstance(t, str))

    return (
        f"ARTICLE METADATA\n"
        f"Title: {title}\n"
        f"Category: {category}\n"
        f"Tags: {tag_list or 'none'}\n\n"
        f"ARTICLE SUMMARY\n{summary or '(none provided)'}\n\n"
        f"ARTICLE BODY\n{body or '(empty)'}\n"
    )


# ── Groq call + parsing ───────────────────────────────────────────────────────


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _coerce_str_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
        if len(out) >= limit:
            break
    return out


def _normalize_analysis(raw: dict, article: dict) -> dict:
    """Coerce Groq output into a safe, predictable schema."""
    sections_raw = raw.get("sections")
    sections: list[dict] = []
    if isinstance(sections_raw, list):
        for s in sections_raw:
            if not isinstance(s, dict):
                continue
            heading = str(s.get("heading", "")).strip()
            body = str(s.get("body", "")).strip()
            if heading and body:
                sections.append({"heading": heading, "body": body})
            if len(sections) >= 6:
                break

    do_dont = raw.get("doAndDont") or {}
    if not isinstance(do_dont, dict):
        do_dont = {}

    try:
        reading_time = max(1, int(raw.get("readingTimeMinutes") or 0))
    except (TypeError, ValueError):
        reading_time = 1
    if reading_time == 1:
        # Fall back to a rough estimate from the article body if Groq omits it.
        words = len((article.get("body") or "").split())
        reading_time = max(1, round(words / 200))

    audience = str(raw.get("audience") or "general").strip().lower()
    if audience not in {"general", "parents", "officers", "clinicians"}:
        audience = "general"

    tone = str(raw.get("tone") or "informative").strip().lower()
    if tone not in {"informative", "urgent", "preventive", "reassuring"}:
        tone = "informative"

    return {
        "version": ANALYSIS_VERSION,
        "tldr": str(raw.get("tldr") or "").strip(),
        "readingTimeMinutes": reading_time,
        "keyPoints": _coerce_str_list(raw.get("keyPoints"), limit=6),
        "sections": sections,
        "doAndDont": {
            "do": _coerce_str_list(do_dont.get("do"), limit=5),
            "dont": _coerce_str_list(do_dont.get("dont"), limit=5),
        },
        "whenToSeekHelp": _coerce_str_list(raw.get("whenToSeekHelp"), limit=5),
        "relatedDiseases": _coerce_str_list(raw.get("relatedDiseases"), limit=6),
        "audience": audience,
        "tone": tone,
        "sourceUpdatedAt": article.get("updatedAt"),
    }


async def _call_groq(article: dict) -> dict | None:
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.warning("[ArticleAnalyzer] GROQ_API_KEY not set — cannot analyze.")
        return None

    payload = {
        "model": _GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(article)},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=_GROQ_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                _GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.RequestError as exc:
        logger.warning("[ArticleAnalyzer] Groq request failed: %s", exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "[ArticleAnalyzer] Groq returned %s: %s",
            resp.status_code,
            resp.text[:300],
        )
        return None

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("[ArticleAnalyzer] Unexpected Groq payload: %s", exc)
        return None

    parsed = _extract_json_object(content)
    if parsed is None:
        logger.warning("[ArticleAnalyzer] Groq response was not valid JSON.")
        return None

    return _normalize_analysis(parsed, article)


# ── Public API ────────────────────────────────────────────────────────────────


async def get_or_create_article_analysis(article: dict) -> dict | None:
    """
    Return a structured analysis for `article`, generating it on a cache miss.

    Returns None only if Groq is unavailable AND nothing is cached — callers
    should treat that as "fall back to raw body".
    """
    article_id = article.get("id")
    if not article_id:
        return None

    key = _cache_key(article_id, article.get("updatedAt"))
    cached = await cache_get_json(key)
    if isinstance(cached, dict):
        return cached

    analysis = await _call_groq(article)
    if analysis is None:
        return None

    await cache_set_json(key, analysis, ttl_seconds=_CACHE_TTL_SECONDS)
    return analysis


async def invalidate_article_analysis(article_id: str) -> int:
    """Drop every cached analysis (across all updatedAt versions) for this article."""
    if not article_id:
        return 0
    return await cache_delete_pattern(_cache_pattern(article_id))
