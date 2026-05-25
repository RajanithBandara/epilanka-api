"""
Health-article controller.

Articles live in MongoDB (collection: `articles`) and are managed by health
officers via the FastAPI REST endpoints in `routes/articleRoute.py`.

Per-user reactions (likes / bookmarks) are owned by the Next.js frontend,
which writes them into the `article_reactions` collection on the same Mongo
database and keeps `likeCount` / `bookmarkCount` denormalised on the article
document. This controller only READS those counters; it never writes to them.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from config.db import get_async_database
from utils.article_analyzer import invalidate_article_analysis


ARTICLES_COLLECTION = "articles"
_indexes_ready = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(title: str) -> str:
    if not title:
        return "article"
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9\s-]", "", text).strip().lower()
    text = re.sub(r"\s+", "-", text)
    return (text[:80] or "article")


def _normalize_string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                out.append(stripped)
    return out


def _normalize_status(value: Any) -> str:
    return "published" if value == "published" else "draft"


def _serialize(doc: dict) -> dict:
    published_at = doc.get("publishedAt")
    return {
        "id": str(doc["_id"]),
        "slug": doc.get("slug", ""),
        "title": doc.get("title", ""),
        "summary": doc.get("summary", ""),
        "body": doc.get("body", ""),
        "tags": doc.get("tags", []) or [],
        "category": doc.get("category", "general"),
        "author": doc.get("author", {"id": "", "name": "", "email": ""}),
        "status": doc.get("status", "draft"),
        "createdAt": (doc["createdAt"].isoformat() if doc.get("createdAt") else None),
        "updatedAt": (doc["updatedAt"].isoformat() if doc.get("updatedAt") else None),
        "publishedAt": (published_at.isoformat() if published_at else None),
        "likeCount": int(doc.get("likeCount", 0) or 0),
        "bookmarkCount": int(doc.get("bookmarkCount", 0) or 0),
    }


async def _articles():
    db = get_async_database()
    collection = db[ARTICLES_COLLECTION]
    global _indexes_ready
    if not _indexes_ready:
        try:
            await collection.create_index("slug", unique=True)
            await collection.create_index([("status", 1), ("publishedAt", -1)])
            await collection.create_index("author.id")
            _indexes_ready = True
        except Exception:
            # Re-attempt on next call; do not block requests on index errors.
            pass
    return collection


async def _unique_slug(base: str, exclude_id: ObjectId | None = None) -> str:
    collection = await _articles()
    slug = base
    suffix = 1
    while True:
        query: dict[str, Any] = {"slug": slug}
        if exclude_id is not None:
            query["_id"] = {"$ne": exclude_id}
        existing = await collection.find_one(query)
        if not existing:
            return slug
        suffix += 1
        slug = f"{base}-{suffix}"


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def create_article(
    author_id: str,
    author_name: str,
    author_email: str,
    title: str,
    summary: str,
    body: str,
    tags: Any = None,
    category: str = "general",
    status: str = "draft",
) -> dict:
    title = (title or "").strip()
    summary = (summary or "").strip()
    body = (body or "").strip()
    if not title:
        raise ValueError("Title is required")
    if not summary:
        raise ValueError("Summary is required")
    if not body:
        raise ValueError("Body is required")

    collection = await _articles()
    now = _utcnow()
    normalized_status = _normalize_status(status)
    slug = await _unique_slug(_slugify(title))

    doc = {
        "_id": ObjectId(),
        "slug": slug,
        "title": title,
        "summary": summary,
        "body": body,
        "tags": _normalize_string_array(tags),
        "category": (category or "general").strip() or "general",
        "author": {
            "id": author_id or "",
            "name": author_name or "",
            "email": author_email or "",
        },
        "status": normalized_status,
        "createdAt": now,
        "updatedAt": now,
        "publishedAt": now if normalized_status == "published" else None,
        "likeCount": 0,
        "bookmarkCount": 0,
    }
    await collection.insert_one(doc)
    return _serialize(doc)


async def update_article(article_id: str, patch: dict) -> dict | None:
    try:
        object_id = ObjectId(article_id)
    except (InvalidId, TypeError):
        return None

    collection = await _articles()
    existing = await collection.find_one({"_id": object_id})
    if not existing:
        return None

    update: dict[str, Any] = {"updatedAt": _utcnow()}

    if "title" in patch:
        title = (patch.get("title") or "").strip()
        if not title:
            raise ValueError("Title cannot be empty")
        update["title"] = title
        if title != existing.get("title"):
            update["slug"] = await _unique_slug(_slugify(title), exclude_id=object_id)

    if "summary" in patch:
        summary = (patch.get("summary") or "").strip()
        if not summary:
            raise ValueError("Summary cannot be empty")
        update["summary"] = summary

    if "body" in patch:
        body = (patch.get("body") or "").strip()
        if not body:
            raise ValueError("Body cannot be empty")
        update["body"] = body

    if "tags" in patch:
        update["tags"] = _normalize_string_array(patch.get("tags"))

    if "category" in patch:
        category = (patch.get("category") or "general").strip() or "general"
        update["category"] = category

    if "status" in patch:
        next_status = _normalize_status(patch.get("status"))
        update["status"] = next_status
        if next_status == "published" and not existing.get("publishedAt"):
            update["publishedAt"] = _utcnow()
        if next_status == "draft":
            update["publishedAt"] = None

    await collection.update_one({"_id": object_id}, {"$set": update})
    doc = await collection.find_one({"_id": object_id})
    # Officer edits must invalidate any previously generated Groq analysis so
    # the user dashboard regenerates against the latest content on next view.
    await invalidate_article_analysis(article_id)
    return _serialize(doc) if doc else None


async def delete_article(article_id: str) -> bool:
    try:
        object_id = ObjectId(article_id)
    except (InvalidId, TypeError):
        return False

    collection = await _articles()
    result = await collection.delete_one({"_id": object_id})
    if result.deleted_count > 0:
        # Cascade: drop the user reactions for this article.
        try:
            db = get_async_database()
            await db["article_reactions"].delete_many({"articleId": article_id})
        except Exception:
            pass
        await invalidate_article_analysis(article_id)
        return True
    return False


async def get_article_by_id(article_id: str) -> dict | None:
    try:
        object_id = ObjectId(article_id)
    except (InvalidId, TypeError):
        return None
    collection = await _articles()
    doc = await collection.find_one({"_id": object_id})
    return _serialize(doc) if doc else None


async def get_article_by_slug(slug: str) -> dict | None:
    if not slug:
        return None
    collection = await _articles()
    doc = await collection.find_one({"slug": slug})
    return _serialize(doc) if doc else None


async def list_articles_for_officers() -> list[dict]:
    collection = await _articles()
    cursor = collection.find({}).sort("updatedAt", -1)
    return [_serialize(doc) async for doc in cursor]


async def list_published_articles() -> list[dict]:
    collection = await _articles()
    cursor = collection.find({"status": "published"}).sort("publishedAt", -1)
    return [_serialize(doc) async for doc in cursor]


# ── Chat context (lightweight projection) ────────────────────────────────────


async def list_published_summaries(limit: int = 30) -> list[dict]:
    collection = await _articles()
    cursor = (
        collection.find(
            {"status": "published"},
            projection={
                "slug": 1,
                "title": 1,
                "summary": 1,
                "tags": 1,
                "category": 1,
                "publishedAt": 1,
            },
        )
        .sort("publishedAt", -1)
        .limit(max(1, min(100, int(limit or 30))))
    )
    out: list[dict] = []
    async for doc in cursor:
        out.append(
            {
                "id": str(doc["_id"]),
                "slug": doc.get("slug", ""),
                "title": doc.get("title", ""),
                "summary": doc.get("summary", ""),
                "tags": doc.get("tags", []) or [],
                "category": doc.get("category", "general"),
                "publishedAt": (
                    doc["publishedAt"].isoformat() if doc.get("publishedAt") else None
                ),
            }
        )
    return out
