from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# Request Schemas
class CreateCommunityRequest(BaseModel):
    name: str
    description: str
    is_public: bool = True
    tags: List[str] = []
    avatar_url: Optional[str] = None

class UpdateCommunityRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    tags: Optional[List[str]] = None
    avatar_url: Optional[str] = None

class CreateThreadRequest(BaseModel):
    title: str
    content: str
    tags: List[str] = []

class UpdateThreadRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    is_pinned: Optional[bool] = None

class CreateMessageRequest(BaseModel):
    content: str
    reply_to: Optional[str] = None
    attachments: List[str] = []

class UpdateMessageRequest(BaseModel):
    content: str

class CreateMemberRequest(BaseModel):
    username: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None

# Response Schemas
class CommunityResponse(BaseModel):
    id: str
    name: str
    description: str
    created_by: str
    created_at: datetime
    member_count: int
    is_public: bool
    tags: List[str]
    avatar_url: Optional[str]

class ThreadResponse(BaseModel):
    id: str
    community_id: str
    title: str
    content: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_activity: datetime
    is_pinned: bool
    tags: List[str]

class MessageResponse(BaseModel):
    id: str
    thread_id: str
    content: str
    author: str
    created_at: datetime
    edited_at: Optional[datetime]
    is_edited: bool
    reply_to: Optional[str]
    attachments: List[str]

class MemberResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    avatar_url: Optional[str]
    bio: Optional[str]
    joined_at: datetime
    is_active: bool
    communities: List[str]

# WebSocket Message Schemas
class WebSocketMessage(BaseModel):
    type: str  # 'new_thread', 'new_message', 'member_joined', etc.
    data: dict
    community_id: Optional[str] = None
    thread_id: Optional[str] = None
    timestamp: datetime = datetime.utcnow()

class JoinRoomMessage(BaseModel):
    action: str = "join"
    community_id: Optional[str] = None
    thread_id: Optional[str] = None
    member_id: str

class LeaveRoomMessage(BaseModel):
    action: str = "leave"
    community_id: Optional[str] = None
    thread_id: Optional[str] = None
    member_id: str
