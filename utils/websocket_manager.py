"""
Socket.IO manager for real-time notifications.
Provides room-based fan-out for user-targeted and broadcast notifications.
"""

from __future__ import annotations

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


def _user_room(user_id: str) -> str:
    return f"{USER_ROOM_PREFIX}{user_id}"


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

socket_app = socketio.ASGIApp(sio, socketio_path="socket.io")


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


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None):
    """Authenticate socket handshake using Appwrite JWT and join rooms."""
    token = _extract_token_from_handshake(environ, auth)
    if not token:
        return False

    try:
        account = get_account_service(token)
        user_obj = account.get()
        user_id = getattr(user_obj, "id", None) or getattr(user_obj, "$id", None)
        if not user_id:
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
        return True
    except AppwriteException:
        return False
    except Exception as exc:
        logger.error("Socket connection error: %s", exc)
        return False


@sio.event
async def disconnect(sid: str):
    await notification_manager.disconnect(sid)


@sio.event
async def ping(sid: str, data=None):
    await sio.emit("pong", {"timestamp": datetime.utcnow().isoformat()}, to=sid)
