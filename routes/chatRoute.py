"""
Chat history routes.

GET    /chat/history          — list all chats for authenticated user
GET    /chat/history/{chatId} — get a single chat
POST   /chat/history/new      — create a new chat session
POST   /chat/history/message  — append a message to a chat
DELETE /chat/history/{chatId} — delete a chat
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from controllers.chatController import (
    create_chat,
    list_chats,
    get_chat,
    append_message,
    delete_chat,
)
from utils.auth_deps import get_current_user, AppwriteUser

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AppendMessageBody(BaseModel):
    chatId: str
    role: str  # "user" | "assistant"
    content: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/history", status_code=status.HTTP_200_OK)
def get_chat_history(user: AppwriteUser = Depends(get_current_user)):
    """Return all chat sessions for the current user, newest first."""
    chats = list_chats(user["$id"])
    return {"chats": chats}


@router.get("/history/{chat_id}", status_code=status.HTTP_200_OK)
def get_single_chat(chat_id: str, user: AppwriteUser = Depends(get_current_user)):
    """Return a single chat session by chatId."""
    chat = get_chat(user["$id"], chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"chat": chat}


@router.post("/history/new", status_code=status.HTTP_201_CREATED)
def new_chat(user: AppwriteUser = Depends(get_current_user)):
    """Create a new empty chat session."""
    result = create_chat(user["$id"])
    return result


@router.post("/history/message", status_code=status.HTTP_200_OK)
def save_message(
    body: AppendMessageBody,
    user: AppwriteUser = Depends(get_current_user),
):
    """Append a message to an existing chat session."""
    if not body.chatId.strip() or body.role not in ("user", "assistant") or not body.content.strip():
        raise HTTPException(status_code=400, detail="chatId, role (user|assistant), and content are required")

    msg = append_message(user["$id"], body.chatId, body.role, body.content)
    if msg is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"ok": True, "message": msg}


@router.delete("/history/{chat_id}", status_code=status.HTTP_200_OK)
def remove_chat(chat_id: str, user: AppwriteUser = Depends(get_current_user)):
    """Delete a chat session."""
    delete_chat(user["$id"], chat_id)
    return {"ok": True}
