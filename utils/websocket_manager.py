"""
WebSocket Manager for Real-time Notifications
Handles WebSocket connections and broadcasts notifications to connected clients
"""

from typing import Dict, Set, List
from fastapi import WebSocket
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Manages WebSocket connections and broadcasts notifications in real-time
    Maintains active connections per user and broadcasts notifications
    """
    
    def __init__(self):
        # Dictionary to store active connections: {user_id: Set[WebSocket]}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """
        Register a new WebSocket connection
        
        Args:
            websocket: The WebSocket connection
            user_id: The user ID for this connection
        """
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        
        self.active_connections[user_id].add(websocket)
        logger.info(f"User {user_id} connected. Total connections: {sum(len(conns) for conns in self.active_connections.values())}")
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        """
        Remove a WebSocket connection
        
        Args:
            websocket: The WebSocket connection to remove
            user_id: The user ID
        """
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            
            # Clean up empty sets
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        logger.info(f"User {user_id} disconnected. Total connections: {sum(len(conns) for conns in self.active_connections.values())}")
    
    async def broadcast_to_user(self, user_id: str, notification: dict):
        """
        Send a notification to a specific user's connections
        
        Args:
            user_id: The target user ID
            notification: The notification data to send
        """
        if user_id in self.active_connections:
            # Create a copy of connections to avoid modification during iteration
            connections = list(self.active_connections[user_id])
            
            dead_connections = []
            for connection in connections:
                try:
                    await connection.send_json({
                        "type": "notification",
                        "data": notification,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                except Exception as e:
                    logger.error(f"Error sending to user {user_id}: {e}")
                    dead_connections.append(connection)
            
            # Clean up dead connections
            for conn in dead_connections:
                self.disconnect(conn, user_id)
    
    async def broadcast_to_all(self, notification: dict, exclude_user: str = None):
        """
        Broadcast a notification to all connected users
        
        Args:
            notification: The notification data to send
            exclude_user: Optional user ID to exclude from broadcast
        """
        all_user_ids = list(self.active_connections.keys())
        
        for user_id in all_user_ids:
            if exclude_user and user_id == exclude_user:
                continue
            
            await self.broadcast_to_user(user_id, notification)
    
    async def send_message_to_user(self, user_id: str, message: dict):
        """
        Send a custom message to a specific user
        
        Args:
            user_id: The target user ID
            message: The message to send
        """
        if user_id in self.active_connections:
            connections = list(self.active_connections[user_id])
            dead_connections = []
            
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending message to user {user_id}: {e}")
                    dead_connections.append(connection)
            
            for conn in dead_connections:
                self.disconnect(conn, user_id)
    
    def get_active_users(self) -> List[str]:
        """
        Get list of currently active user IDs
        
        Returns:
            List of user IDs with active connections
        """
        return list(self.active_connections.keys())
    
    def get_connection_count(self, user_id: str = None) -> int:
        """
        Get the number of active connections
        
        Args:
            user_id: Optional user ID to get count for specific user
            
        Returns:
            int: Number of connections
        """
        if user_id:
            return len(self.active_connections.get(user_id, set()))
        
        return sum(len(conns) for conns in self.active_connections.values())
    
    async def send_status_update(self, user_id: str):
        """
        Send a connection status update to a user
        
        Args:
            user_id: The target user ID
        """
        await self.send_message_to_user(user_id, {
            "type": "connection",
            "status": "connected",
            "timestamp": datetime.utcnow().isoformat()
        })


# Global notification manager instance
notification_manager = NotificationManager()
