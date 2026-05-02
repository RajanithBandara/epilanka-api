"""
Chat history controller — persists chat sessions using Appwrite SDK v17 TablesDB.

Terminology in v17:
  Databases  → deprecated for DB/collection management
  TablesDB   → current API (database → table → rows)
  row.id     → the $id system field
  row.data   → dict of user-defined column values (when model_type=dict)
  RowList.rows → list of Row objects

Environment variables:
  APPWRITE_CHAT_DB_ID         — Database ID
  APPWRITE_CHAT_COLLECTION_ID — Table ID (env key kept for backward compat)
"""

import json
import os
import uuid
from datetime import datetime, timezone

from appwrite.services.tables_db import TablesDB
from appwrite.query import Query
from appwrite.id import ID

from utils.appwrite_client import get_server_client

CHAT_DB_ID = os.getenv("APPWRITE_CHAT_DB_ID", "")
CHAT_TABLE_ID = os.getenv("APPWRITE_CHAT_COLLECTION_ID", "")
MAX_MESSAGES = 100


def _db() -> TablesDB:
    return TablesDB(get_server_client())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_chat_id() -> str:
    return uuid.uuid4().hex


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_chat(row) -> dict:
    """
    Convert a TablesDB Row to a clean chat dict.
    row.data is a plain dict of user columns (since we use model_type=dict).
    """
    d: dict = row.data if isinstance(row.data, dict) else {}

    try:
        messages = json.loads(d.get("messages", "[]"))
    except (json.JSONDecodeError, TypeError):
        messages = []

    return {
        "id": d.get("chatId", ""),
        "title": d.get("title", "New Chat"),
        "messages": messages,
        "createdAt": d.get("createdAt", ""),
        "updatedAt": d.get("updatedAt", ""),
    }


def _get_row_id(row) -> str:
    """Return the system $id of a Row object."""
    return row.id  # Row.id is aliased from $id in the Pydantic model


# ── Create ────────────────────────────────────────────────────────────────────

def create_chat(user_id: str) -> dict:
    db = _db()
    now = _now()
    chat_id = _new_chat_id()

    db.create_row(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        row_id=ID.unique(),
        data={
            "userId": user_id,
            "chatId": chat_id,
            "title": "New Chat",
            "messages": json.dumps([]),
            "createdAt": now,
            "updatedAt": now,
        },
    )

    return {
        "chatId": chat_id,
        "chat": {
            "id": chat_id,
            "title": "New Chat",
            "messages": [],
            "createdAt": now,
            "updatedAt": now,
        },
    }


# ── Read ──────────────────────────────────────────────────────────────────────

def list_chats(user_id: str) -> list[dict]:
    db = _db()
    result = db.list_rows(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        queries=[
            Query.equal("userId", user_id),
            Query.order_desc("updatedAt"),
            Query.limit(50),
        ],
    )
    return [_row_to_chat(r) for r in result.rows]


def get_chat(user_id: str, chat_id: str) -> dict | None:
    db = _db()
    result = db.list_rows(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        queries=[
            Query.equal("userId", user_id),
            Query.equal("chatId", chat_id),
            Query.limit(1),
        ],
    )
    if not result.rows:
        return None
    return _row_to_chat(result.rows[0])


# ── Append message ─────────────────────────────────────────────────────────────

def append_message(user_id: str, chat_id: str, role: str, content: str) -> dict | None:
    db = _db()

    result = db.list_rows(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        queries=[
            Query.equal("userId", user_id),
            Query.equal("chatId", chat_id),
            Query.limit(1),
        ],
    )
    if not result.rows:
        return None

    row = result.rows[0]
    row_id = _get_row_id(row)
    d: dict = row.data if isinstance(row.data, dict) else {}

    try:
        messages: list = json.loads(d.get("messages", "[]"))
    except (json.JSONDecodeError, TypeError):
        messages = []

    now = _now()
    new_message = {"role": role, "content": content.strip(), "createdAt": now}
    messages = (messages + [new_message])[-MAX_MESSAGES:]

    db.update_row(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        row_id=row_id,
        data={"messages": json.dumps(messages), "updatedAt": now},
    )
    return new_message


# ── Delete ─────────────────────────────────────────────────────────────────────

def delete_chat(user_id: str, chat_id: str) -> bool:
    db = _db()

    result = db.list_rows(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        queries=[
            Query.equal("userId", user_id),
            Query.equal("chatId", chat_id),
            Query.limit(1),
        ],
    )
    if not result.rows:
        return True

    db.delete_row(
        database_id=CHAT_DB_ID,
        table_id=CHAT_TABLE_ID,
        row_id=_get_row_id(result.rows[0]),
    )
    return True
