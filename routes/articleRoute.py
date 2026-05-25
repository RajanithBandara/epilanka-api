"""
Article REST endpoints.

Officer endpoints (require an Appwrite JWT with the `officer` label):
  GET    /articles/officer            list all (any status)
  POST   /articles/officer            create
  GET    /articles/officer/{id}       read one
  PUT    /articles/officer/{id}       update (any officer can edit any article)
  DELETE /articles/officer/{id}       delete (cascades to article_reactions)

Public endpoints (no auth — non-sensitive):
  GET    /articles/public             list published
  GET    /articles/public/{id-or-slug}
  GET    /articles/summaries          lightweight projection used by the chatbot

Per-user likes / bookmarks are NOT handled here. They are owned by the
Next.js frontend (see /api/articles/[id]/like and /bookmark), which writes
to the `article_reactions` collection on the same Mongo database and
denormalises `likeCount` / `bookmarkCount` back onto the article doc.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from controllers.articleController import (
    create_article,
    delete_article,
    get_article_by_id,
    get_article_by_slug,
    list_articles_for_officers,
    list_published_articles,
    list_published_summaries,
    update_article,
)
from utils.article_analyzer import get_or_create_article_analysis
from utils.auth_deps import AppwriteUser, get_current_officer


router = APIRouter(prefix="/articles", tags=["articles"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class ArticleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=400)
    body: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    category: str = Field(default="general", max_length=80)
    status: str = Field(default="draft")  # "draft" | "published"


class ArticleUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=400)
    body: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = Field(default=None, max_length=80)
    status: Optional[str] = None


# ── Officer endpoints ────────────────────────────────────────────────────────


@router.get("/officer", status_code=200)
async def officer_list_articles(_: AppwriteUser = Depends(get_current_officer)):
    articles = await list_articles_for_officers()
    return {"articles": articles}


@router.post("/officer", status_code=status.HTTP_201_CREATED)
async def officer_create_article(
    payload: ArticleCreate,
    current: AppwriteUser = Depends(get_current_officer),
):
    try:
        return await create_article(
            author_id=current.get("$id") or "",
            author_name=current.get("name") or "",
            author_email=current.get("email") or "",
            title=payload.title,
            summary=payload.summary,
            body=payload.body,
            tags=payload.tags,
            category=payload.category,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/officer/{article_id}", status_code=200)
async def officer_get_article(
    article_id: str,
    _: AppwriteUser = Depends(get_current_officer),
):
    article = await get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.put("/officer/{article_id}", status_code=200)
async def officer_update_article(
    article_id: str,
    payload: ArticleUpdate,
    _: AppwriteUser = Depends(get_current_officer),
):
    patch = payload.model_dump(exclude_unset=True)
    try:
        updated = await update_article(article_id, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="Article not found")
    return updated


@router.delete("/officer/{article_id}", status_code=200)
async def officer_delete_article(
    article_id: str,
    _: AppwriteUser = Depends(get_current_officer),
):
    ok = await delete_article(article_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"ok": True}


# ── Public endpoints ─────────────────────────────────────────────────────────


@router.get("/public", status_code=200)
async def public_list_articles():
    """Published articles only. Reactions are merged in by the Next.js layer."""
    articles = await list_published_articles()
    return {"articles": articles}


@router.get("/public/{identifier}", status_code=200)
async def public_get_article(identifier: str):
    """Looks up by Mongo ObjectId first, then by slug."""
    article = await get_article_by_id(identifier)
    if not article:
        article = await get_article_by_slug(identifier)
    if not article or article.get("status") != "published":
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.get("/public/{identifier}/analysis", status_code=200)
async def public_get_article_analysis(identifier: str):
    """
    Return the Groq-generated, user-friendly structured analysis for an article.

    First call for a given article generates + caches in Redis; subsequent
    calls are served from cache. Officer edits invalidate the cache.
    """
    article = await get_article_by_id(identifier)
    if not article:
        article = await get_article_by_slug(identifier)
    if not article or article.get("status") != "published":
        raise HTTPException(status_code=404, detail="Article not found")

    analysis = await get_or_create_article_analysis(article)
    return {
        "articleId": article["id"],
        "updatedAt": article.get("updatedAt"),
        "analysis": analysis,
    }


@router.get("/summaries", status_code=200)
async def get_summaries(limit: int = Query(default=30, ge=1, le=100)):
    """Lightweight projection consumed by the EpiGuard chat for grounding."""
    summaries = await list_published_summaries(limit=limit)
    return {"articles": summaries}
