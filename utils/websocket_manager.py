"""
Socket.IO manager for real-time notifications.
Provides room-based fan-out for user-targeted and broadcast notifications.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List
from urllib.parse import parse_qs
import logging

import socketio
from appwrite.exception import AppwriteException

from utils.appwrite_client import get_account_service

logger = logging.getLogger(__name__)

GLOBAL_NOTIFICATION_ROOM = "notifications:all"
USER_ROOM_PREFIX = "notifications:user:"

# Thread pool for running blocking Appwrite SDK calls
# without blocking the async event loop.
_thread_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="sio-auth")


def _user_room(user_id: str) -> str:
    return f"{USER_ROOM_PREFIX}{user_id}"


# ── Socket.IO server configuration ──────────────────────────────────────────
# ping_interval: how often (seconds) the server sends a ping to the client.
# ping_timeout:  how long (seconds) the server waits for a pong before
#                considering the connection dead.
# Tuned for cloud hosting (Railway / Render) where idle TCP connections can be
# dropped by the load balancer after ~30 s of inactivity.
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
    ping_interval=20,            # send ping every 20 s
    ping_timeout=15,             # wait 15 s for pong before disconnect
    max_http_buffer_size=1_048_576,  # 1 MB max payload
)

socket_app = socketio.ASGIApp(sio, socketio_path="socket.io")


def _verify_token_sync(token: str) -> str | None:
    """
    Verify an Appwrite JWT synchronously.
    Returns the user_id string on success, None on any failure.
    This is intentionally a plain function (not async) so it can run
    in a thread pool without blocking the event loop.
    """
    try:
        account = get_account_service(token)
        user_obj = account.get()
        user_id = getattr(user_obj, "id", None) or getattr(user_obj, "$id", None)
        return user_id or None
    except AppwriteException as exc:
        logger.warning("Appwrite token verification failed: %s", exc.message)
        return None
    except Exception as exc:
        logger.error("Unexpected error during token verification: %s", exc)
        return None


async def _verify_token_async(token: str, timeout: float = 8.0) -> str | None:
    """
    Run the blocking Appwrite SDK call in a thread pool so the async
    event loop is never blocked.  Returns user_id or None.
    """
    loop = asyncio.get_event_loop()
    try:
        user_id = await asyncio.wait_for(
            loop.run_in_executor(_thread_pool, _verify_token_sync, token),
            timeout=timeout,
        )
        return user_id
    except asyncio.TimeoutError:
        logger.warning("Token verification timed out after %.1f s", timeout)
        return None
    except Exception as exc:
        logger.error("Async token verification wrapper error: %s", exc)
        return None


class NotificationManager:
    """
    Manages Socket.IO connections and room-based notification broadcasts.
    """

    def __init__(self):
        # Tracks the authenticated user mapped by Socket.IO session id.
        self.sid_to_user: Dict[str, str] = {}

    async def connect(self, sid: str, user_id: str):
        """Register a connected Socket.IO client into its rooms."""
        self.sid_to_user[sid] = user_id
        await sio.enter_room(sid, GLOBAL_NOTIFICATION_ROOM)
        await sio.enter_room(sid, _user_room(user_id))
        logger.info("User %s connected with sid %s", user_id, sid)

    async def disconnect(self, sid: str):
        """Remove a disconnected Socket.IO client from tracking."""
        user_id = self.sid_to_user.pop(sid, None)
        if user_id:
            await sio.leave_room(sid, GLOBAL_NOTIFICATION_ROOM)
            await sio.leave_room(sid, _user_room(user_id))
            logger.info("User %s disconnected with sid %s", user_id, sid)

    async def broadcast_to_user(self, user_id: str, payload: dict, event_name: str = "notification"):
        """Emit an event payload to the room for one user."""
        await sio.emit(event_name, payload, room=_user_room(user_id))

    async def broadcast_to_all(self, payload: dict, exclude_user: str = None, event_name: str = "notification"):
        """Broadcast an event payload to all connected users, optionally excluding one user."""
        if not exclude_user:
            await sio.emit(event_name, payload, room=GLOBAL_NOTIFICATION_ROOM)
            return

        for sid, user_id in list(self.sid_to_user.items()):
            if user_id == exclude_user:
                continue
            await sio.emit(event_name, payload, to=sid)

    async def send_message_to_user(self, user_id: str, message: dict):
        """Emit a custom event payload to one user room."""
        await sio.emit("message", message, room=_user_room(user_id))

    def get_active_users(self) -> List[str]:
        """Get all currently connected user IDs."""
        return list({user_id for user_id in self.sid_to_user.values()})

    def get_connection_count(self, user_id: str = None) -> int:
        """Get active connection count globally or for one user."""
        if user_id:
            return sum(1 for uid in self.sid_to_user.values() if uid == user_id)
        return len(self.sid_to_user)

    async def send_status_update(self, user_id: str):
        """Send a connection status update to a user room."""
        await self.send_message_to_user(user_id, {
            "event": "connection",
            "status": "connected",
            "timestamp": datetime.utcnow().isoformat()
        })


# Global notification manager instance
notification_manager = NotificationManager()


def _extract_token_from_handshake(environ: dict, auth: dict | None) -> str | None:
    """
    Try to extract the JWT from:
      1. The Socket.IO auth payload  { token: "..." }
      2. The QUERY_STRING            ?token=...
    """
    if isinstance(auth, dict):
        token = auth.get("token")
        if token:
            return token

    query_string = environ.get("QUERY_STRING", "")
    if query_string:
        params = parse_qs(query_string)
        values = params.get("token")
        if values:
            return values[0]

    return None


# ── Socket.IO event handlers ─────────────────────────────────────────────────

@sio.event
async def connect(sid: str, environ: dict, auth: dict | None):
    """
    Authenticate socket handshake using Appwrite JWT.

    The Appwrite SDK call is blocking (synchronous HTTP), so we run it in a
    thread pool to prevent blocking the asyncio event loop — which was the
    main cause of 403 rejections.
    """
    token = _extract_token_from_handshake(environ, auth)
    if not token:
        logger.warning("Socket rejected — no token in handshake (sid=%s)", sid)
        return False  # reject connection

    logger.debug("Verifying token for sid=%s ...", sid)
    user_id = await _verify_token_async(token)

    if not user_id:
        logger.warning("Socket rejected — token verification returned no user_id (sid=%s)", sid)
        return False

    await notification_manager.connect(sid, user_id)
    await sio.emit(
        "connection",
        {
            "status": "connected",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
        },
        to=sid,
    )
    logger.info("Socket accepted for user_id=%s (sid=%s)", user_id, sid)
    return True


@sio.event
async def disconnect(sid: str):
    await notification_manager.disconnect(sid)


@sio.event
async def ping(sid: str, data=None):
    """Lightweight application-level ping for latency checking."""
    await sio.emit("pong", {"timestamp": datetime.utcnow().isoformat()}, to=sid)


@sio.event
async def refresh_token(sid: str, data: dict | None):
    """
    Client sends a fresh Appwrite JWT without disconnecting.

    The frontend should call this ~1 minute before the JWT expires (Appwrite
    JWTs expire after 15 minutes).  The server re-verifies the new token and
    updates the user mapping so the connection remains authenticated.

    Emits:
        token_refreshed       — on success
        token_refresh_error   — on failure (client should reconnect)
    """
    if not isinstance(data, dict):
        await sio.emit("token_refresh_error", {"error": "Invalid payload"}, to=sid)
        return

    new_token = data.get("token")
    if not new_token:
        await sio.emit("token_refresh_error", {"error": "Token missing"}, to=sid)
        return

    new_user_id = await _verify_token_async(new_token)

    if not new_user_id:
        logger.warning("Token refresh rejected — verification failed (sid=%s)", sid)
        await sio.emit("token_refresh_error", {"error": "Token expired or invalid"}, to=sid)
        return

    old_user_id = notification_manager.sid_to_user.get(sid)

    # If the user identity changed (shouldn't happen in normal flow), update rooms.
    if old_user_id and old_user_id != new_user_id:
        await sio.leave_room(sid, _user_room(old_user_id))
        await sio.enter_room(sid, _user_room(new_user_id))
        notification_manager.sid_to_user[sid] = new_user_id
        logger.info("Token refresh: user changed %s → %s (sid=%s)", old_user_id, new_user_id, sid)
    else:
        notification_manager.sid_to_user[sid] = new_user_id

    await sio.emit(
        "token_refreshed",
        {
            "user_id": new_user_id,
            "timestamp": datetime.utcnow().isoformat(),
        },
        to=sid,
    )
    logger.info("Token refreshed for user %s (sid=%s)", new_user_id, sid)
