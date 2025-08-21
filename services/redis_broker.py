import asyncio
import json
import redis.asyncio as redis
from typing import Optional, Callable, Dict, Any
import logging

from bson import ObjectId

from api.routes.auth import db

logger = logging.getLogger(__name__)


class RedisBroker:
    def __init__(self, redis_url: str = "redis://localhost:6379", redis_password: Optional[str] = None):
        self.redis_url = redis_url
        self.redis_password = redis_password
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub = None
        self.subscribers: Dict[str, Callable] = {}

    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                password=self.redis_password,
                decode_responses=True
            )
            self.pubsub = self.redis_client.pubsub()
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("Disconnected from Redis")

    async def publish(self, channel: str, message: Dict[Any, Any]):
        """Publish a message to a Redis channel"""
        if not self.redis_client:
            raise RuntimeError("Redis client not connected")

        try:
            message_str = json.dumps(message, default=str)
            await self.redis_client.publish(channel, message_str)
            logger.debug(f"Published message to channel {channel}: {message}")
        except Exception as e:
            logger.error(f"Failed to publish message to {channel}: {e}")
            raise

    async def subscribe(self, channel: str, callback: Callable):
        """Subscribe to a Redis channel with a callback"""
        if not self.pubsub:
            raise RuntimeError("Redis pubsub not initialized")

        try:
            await self.pubsub.subscribe(channel)
            self.subscribers[channel] = callback
            logger.info(f"Subscribed to channel: {channel}")
        except Exception as e:
            logger.error(f"Failed to subscribe to {channel}: {e}")
            raise

    async def unsubscribe(self, channel: str):
        """Unsubscribe from a Redis channel"""
        if not self.pubsub:
            return

        try:
            await self.pubsub.unsubscribe(channel)
            if channel in self.subscribers:
                del self.subscribers[channel]
            logger.info(f"Unsubscribed from channel: {channel}")
        except Exception as e:
            logger.error(f"Failed to unsubscribe from {channel}: {e}")

    async def listen(self):
        """Listen for messages on subscribed channels"""
        if not self.pubsub:
            raise RuntimeError("Redis pubsub not initialized")

        try:
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    channel = message['channel']
                    data = json.loads(message['data'])

                    if channel in self.subscribers:
                        callback = self.subscribers[channel]
                        try:
                            await callback(channel, data)
                        except Exception as e:
                            logger.error(f"Error in callback for channel {channel}: {e}")
        except Exception as e:
            logger.error(f"Error listening to Redis messages: {e}")

    # Channel name generators for different message types
    @staticmethod
    def get_community_channel(community_id: str) -> str:
        return f"community:{community_id}"

    @staticmethod
    def get_thread_channel(thread_id: str) -> str:
        return f"thread:{thread_id}"

    @staticmethod
    def get_global_channel() -> str:
        return "global:notifications"


# Global broker instance
redis_broker = RedisBroker()


# Message types for different events
class MessageTypes:
    NEW_THREAD = "new_thread"
    NEW_MESSAGE = "new_message"
    THREAD_UPDATED = "thread_updated"
    MESSAGE_UPDATED = "message_updated"
    MESSAGE_DELETED = "message_deleted"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    TYPING = "typing"
    STOP_TYPING = "stop_typing"

def publish_thread_event(thread_data: dict, event_type: str = MessageTypes.NEW_THREAD):
    """Publish thread-related events"""
    community_id = thread_data.get('community_id')

    if community_id:
        thread_data['created_by'] = thread_data.get('author')
        channel = RedisBroker.get_community_channel(community_id)
        message = {
            'type': event_type,
            'data': thread_data,
            'timestamp': thread_data.get('created_at') or thread_data.get('updated_at')
        }

        # Publish to Redis
        asyncio.run(redis_broker.publish(channel, message))


def publish_message_event(message_data: dict, event_type: str = MessageTypes.NEW_MESSAGE):
    """Publish message-related events"""
    print("publishing:" + MessageTypes.NEW_MESSAGE)
    thread_id = message_data.get('thread_id')
    if thread_id:
        channel = RedisBroker.get_thread_channel(thread_id)
        message = {
            'type': event_type,
            'data': message_data,
            'timestamp': message_data.get('created_at') or message_data.get('updated_at')
        }
        redis_broker.publish(channel, message)


def publish_member_event(member_data: dict, community_id: str, event_type: str):
    """Publish member-related events"""
    channel = RedisBroker.get_community_channel(community_id)
    message = {
        'type': event_type,
        'data': member_data,
        'community_id': community_id,
        'timestamp': member_data.get('joined_at')
    }
    redis_broker.publish(channel, message)
