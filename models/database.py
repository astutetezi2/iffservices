from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import os
from datetime import datetime
from bson import ObjectId
from pydantic import BaseModel, Field
from typing import List, Optional, Any

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")

# Database Models
class Community(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str
    description: str
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    member_count: int = 0
    is_public: bool = True
    tags: List[str] = []
    avatar_url: Optional[str] = None

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Thread(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    community_id: str
    title: str
    content: str
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    message_count: int = 0
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    is_pinned: bool = False
    tags: List[str] = []

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Message(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    thread_id: str
    content: str
    author: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = None
    is_edited: bool = False
    reply_to: Optional[str] = None
    attachments: List[str] = []

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Member(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    username: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
    communities: List[str] = []

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

# Database Connection
class Database:
    client: Optional[AsyncIOMotorClient] = None
    database = None

    @classmethod
    async def connect_to_mongo(cls):
        cls.client = AsyncIOMotorClient("mongodb://localhost:27017")
        cls.database = cls.client.communities_db
        
        # Create indexes for better performance
        await cls.create_indexes()

    @classmethod
    async def close_mongo_connection(cls):
        if cls.client:
            cls.client.close()

    @classmethod
    async def create_indexes(cls):
        # Communities indexes
        await cls.database.communities.create_index("name")
        await cls.database.communities.create_index("created_by")
        await cls.database.communities.create_index("is_public")
        
        # Threads indexes
        await cls.database.threads.create_index("community_id")
        await cls.database.threads.create_index("created_by")
        await cls.database.threads.create_index("last_activity")
        await cls.database.threads.create_index([("community_id", 1), ("last_activity", -1)])
        
        # Messages indexes
        await cls.database.messages.create_index("thread_id")
        await cls.database.messages.create_index("author")
        await cls.database.messages.create_index("created_at")
        await cls.database.messages.create_index([("thread_id", 1), ("created_at", 1)])
        
        # Members indexes
        await cls.database.members.create_index("username", unique=True)
        await cls.database.members.create_index("email", unique=True)

database = Database()
