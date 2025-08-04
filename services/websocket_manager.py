import asyncio
import json
from typing import Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Store active connections by community and thread
        self.community_connections: Dict[str, Set[WebSocket]] = {}
        self.thread_connections: Dict[str, Set[WebSocket]] = {}
        self.user_connections: Dict[str, WebSocket] = {}
        self.connection_metadata: Dict[WebSocket, Dict] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        self.user_connections[user_id] = websocket
        self.connection_metadata[websocket] = {
            'user_id': user_id,
            'connected_at': datetime.utcnow(),
            'communities': set(),
            'threads': set()
        }
        logger.info(f"User {user_id} connected via WebSocket")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.connection_metadata:
            metadata = self.connection_metadata[websocket]
            user_id = metadata['user_id']
            
            # Remove from all community channels
            for community_id in metadata['communities']:
                if community_id in self.community_connections:
                    self.community_connections[community_id].discard(websocket)
                    if not self.community_connections[community_id]:
                        del self.community_connections[community_id]
            
            # Remove from all thread channels
            for thread_id in metadata['threads']:
                if thread_id in self.thread_connections:
                    self.thread_connections[thread_id].discard(websocket)
                    if not self.thread_connections[thread_id]:
                        del self.thread_connections[thread_id]
            
            # Remove from user connections
            if user_id in self.user_connections:
                del self.user_connections[user_id]
            
            del self.connection_metadata[websocket]
            logger.info(f"User {user_id} disconnected")

    async def join_community(self, websocket: WebSocket, community_id: str):
        """Add connection to a community channel"""
        if community_id not in self.community_connections:
            self.community_connections[community_id] = set()
        
        self.community_connections[community_id].add(websocket)
        
        if websocket in self.connection_metadata:
            self.connection_metadata[websocket]['communities'].add(community_id)
        
        logger.info(f"WebSocket joined community {community_id}")

    async def leave_community(self, websocket: WebSocket, community_id: str):
        """Remove connection from a community channel"""
        if community_id in self.community_connections:
            self.community_connections[community_id].discard(websocket)
            if not self.community_connections[community_id]:
                del self.community_connections[community_id]
        
        if websocket in self.connection_metadata:
            self.connection_metadata[websocket]['communities'].discard(community_id)
        
        logger.info(f"WebSocket left community {community_id}")

    async def join_thread(self, websocket: WebSocket, thread_id: str):
        """Add connection to a thread channel"""
        if thread_id not in self.thread_connections:
            self.thread_connections[thread_id] = set()
        
        self.thread_connections[thread_id].add(websocket)
        
        if websocket in self.connection_metadata:
            self.connection_metadata[websocket]['threads'].add(thread_id)
        
        logger.info(f"WebSocket joined thread {thread_id}")

    async def leave_thread(self, websocket: WebSocket, thread_id: str):
        """Remove connection from a thread channel"""
        if thread_id in self.thread_connections:
            self.thread_connections[thread_id].discard(websocket)
            if not self.thread_connections[thread_id]:
                del self.thread_connections[thread_id]
        
        if websocket in self.connection_metadata:
            self.connection_metadata[websocket]['threads'].discard(thread_id)
        
        logger.info(f"WebSocket left thread {thread_id}")

    async def send_personal_message(self, user_id: str, message: dict):
        """Send message to a specific user"""
        if user_id in self.user_connections:
            websocket = self.user_connections[user_id]
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending personal message to {user_id}: {e}")
                self.disconnect(websocket)

    async def broadcast_to_community(self, community_id: str, message: dict):
        """Broadcast message to all connections in a community"""
        if community_id in self.community_connections:
            disconnected = []
            
            for websocket in self.community_connections[community_id].copy():
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"Error broadcasting to community {community_id}: {e}")
                    disconnected.append(websocket)
            
            # Clean up disconnected sockets
            for websocket in disconnected:
                self.disconnect(websocket)

    async def broadcast_to_thread(self, thread_id: str, message: dict):
        """Broadcast message to all connections in a thread"""
        if thread_id in self.thread_connections:
            disconnected = []
            
            for websocket in self.thread_connections[thread_id].copy():
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"Error broadcasting to thread {thread_id}: {e}")
                    disconnected.append(websocket)
            
            # Clean up disconnected sockets
            for websocket in disconnected:
                self.disconnect(websocket)

    async def broadcast_to_all(self, message: dict):
        """Broadcast message to all connected users"""
        disconnected = []
        
        for websocket in list(self.connection_metadata.keys()):
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting to all: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected sockets
        for websocket in disconnected:
            self.disconnect(websocket)

    def get_connection_count(self) -> int:
        """Get total number of active connections"""
        return len(self.connection_metadata)

    def get_community_connection_count(self, community_id: str) -> int:
        """Get number of connections in a specific community"""
        return len(self.community_connections.get(community_id, set()))

    def get_thread_connection_count(self, thread_id: str) -> int:
        """Get number of connections in a specific thread"""
        return len(self.thread_connections.get(thread_id, set()))

# Global connection manager instance
manager = ConnectionManager()

# WebSocket message handlers
async def handle_websocket_message(websocket: WebSocket, message: dict):
    """Handle incoming WebSocket messages"""
    action = message.get('action')
    
    try:
        if action == 'join_community':
            community_id = message.get('community_id')
            if community_id:
                await manager.join_community(websocket, community_id)
                
        elif action == 'leave_community':
            community_id = message.get('community_id')
            if community_id:
                await manager.leave_community(websocket, community_id)
                
        elif action == 'join_thread':
            thread_id = message.get('thread_id')
            if thread_id:
                await manager.join_thread(websocket, thread_id)
                
        elif action == 'leave_thread':
            thread_id = message.get('thread_id')
            if thread_id:
                await manager.leave_thread(websocket, thread_id)
                
        elif action == 'typing':
            thread_id = message.get('thread_id')
            user_id = message.get('user_id')
            if thread_id and user_id:
                typing_message = {
                    'type': 'typing',
                    'thread_id': thread_id,
                    'user_id': user_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
                await manager.broadcast_to_thread(thread_id, typing_message)
                
        elif action == 'stop_typing':
            thread_id = message.get('thread_id')
            user_id = message.get('user_id')
            if thread_id and user_id:
                stop_typing_message = {
                    'type': 'stop_typing',
                    'thread_id': thread_id,
                    'user_id': user_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
                await manager.broadcast_to_thread(thread_id, stop_typing_message)
                
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")
        error_message = {
            'type': 'error',
            'message': 'Failed to process message',
            'timestamp': datetime.utcnow().isoformat()
        }
        await websocket.send_text(json.dumps(error_message))
