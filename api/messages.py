from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from models.database import database, Message
from schemas.api_schemas import (
    CreateMessageRequest, 
    UpdateMessageRequest, 
    MessageResponse
)
from services.redis_broker import publish_message_event, MessageTypes

router = APIRouter(prefix="/messages", tags=["messages"])

def convert_message_to_response(message: dict) -> MessageResponse:
    """Convert database message document to response schema"""
    message['id'] = str(message['_id'])
    del message['_id']
    return MessageResponse(**message)

@router.get("/thread/{thread_id}", response_model=List[MessageResponse])
async def get_thread_messages(
    thread_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    sort_order: str = Query("asc", regex="^(asc|desc)$")
):
    """Get all messages in a thread"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    
    try:
        # Check if thread exists
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        # Build sort criteria
        sort_direction = 1 if sort_order == "asc" else -1
        
        cursor = (database.database.messages
                 .find({"thread_id": thread_id})
                 .sort([("created_at", sort_direction)])
                 .skip(skip)
                 .limit(limit))
        
        messages = await cursor.to_list(length=limit)
        
        return [convert_message_to_response(message) for message in messages]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch messages: {str(e)}")

@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(message_id: str):
    """Get a specific message by ID"""
    if not ObjectId.is_valid(message_id):
        raise HTTPException(status_code=400, detail="Invalid message ID")
    
    try:
        message = await database.database.messages.find_one({"_id": ObjectId(message_id)})
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        return convert_message_to_response(message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch message: {str(e)}")

@router.post("/thread/{thread_id}", response_model=MessageResponse, status_code=201)
async def create_message(
    thread_id: str, 
    message_data: CreateMessageRequest, 
    author: str = "user123"  # TODO: Get from auth
):
    """Create a new message in a thread"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    
    try:
        # Check if thread exists
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        # Check if user is a member of the community
        community_id = thread["community_id"]
        member = await database.database.members.find_one({
            "username": author,
            "communities": community_id
        })
        if not member:
            raise HTTPException(status_code=403, detail="You must be a member of the community to post messages")
        
        # Validate reply_to if provided
        if message_data.reply_to:
            if not ObjectId.is_valid(message_data.reply_to):
                raise HTTPException(status_code=400, detail="Invalid reply_to message ID")
            
            reply_message = await database.database.messages.find_one({
                "_id": ObjectId(message_data.reply_to),
                "thread_id": thread_id
            })
            if not reply_message:
                raise HTTPException(status_code=404, detail="Reply target message not found in this thread")
        
        message_dict = message_data.dict()
        message_dict["thread_id"] = thread_id
        message_dict["author"] = author
        message_dict["created_at"] = datetime.utcnow()
        message_dict["is_edited"] = False
        
        result = await database.database.messages.insert_one(message_dict)
        
        # Update thread message count and last activity
        await database.database.threads.update_one(
            {"_id": ObjectId(thread_id)},
            {
                "$inc": {"message_count": 1},
                "$set": {"last_activity": datetime.utcnow()}
            }
        )
        
        # Fetch the created message
        created_message = await database.database.messages.find_one({"_id": result.inserted_id})
        
        # Publish message creation event
        message_response = convert_message_to_response(created_message.copy())
        await publish_message_event(message_response.dict(), MessageTypes.NEW_MESSAGE)
        
        return message_response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create message: {str(e)}")

@router.put("/{message_id}", response_model=MessageResponse)
async def update_message(
    message_id: str, 
    message_data: UpdateMessageRequest, 
    user_id: str = "user123"  # TODO: Get from auth
):
    """Update a message (edit content)"""
    if not ObjectId.is_valid(message_id):
        raise HTTPException(status_code=400, detail="Invalid message ID")
    
    try:
        # Check if message exists and user has permission
        message = await database.database.messages.find_one({"_id": ObjectId(message_id)})
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        if message["author"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to update this message")
        
        # Update message
        update_data = {
            "content": message_data.content,
            "edited_at": datetime.utcnow(),
            "is_edited": True
        }
        
        await database.database.messages.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": update_data}
        )
        
        # Fetch updated message
        updated_message = await database.database.messages.find_one({"_id": ObjectId(message_id)})
        message_response = convert_message_to_response(updated_message)
        
        # Publish message update event
        await publish_message_event(message_response.dict(), MessageTypes.MESSAGE_UPDATED)
        
        return message_response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update message: {str(e)}")

@router.delete("/{message_id}", status_code=204)
async def delete_message(message_id: str, user_id: str = "user123"):  # TODO: Get from auth
    """Delete a message"""
    if not ObjectId.is_valid(message_id):
        raise HTTPException(status_code=400, detail="Invalid message ID")
    
    try:
        # Check if message exists and user has permission
        message = await database.database.messages.find_one({"_id": ObjectId(message_id)})
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Check permission (message author or community admin)
        if message["author"] != user_id:
            # Check if user is community admin
            thread = await database.database.threads.find_one({"_id": ObjectId(message["thread_id"])})
            if thread:
                community = await database.database.communities.find_one({"_id": ObjectId(thread["community_id"])})
                if not community or community["created_by"] != user_id:
                    raise HTTPException(status_code=403, detail="Not authorized to delete this message")
        
        # Delete the message
        await database.database.messages.delete_one({"_id": ObjectId(message_id)})
        
        # Update thread message count
        await database.database.threads.update_one(
            {"_id": ObjectId(message["thread_id"])},
            {"$inc": {"message_count": -1}}
        )
        
        # Publish message deletion event
        deletion_event = {
            "id": message_id,
            "thread_id": message["thread_id"],
            "deleted_by": user_id,
            "deleted_at": datetime.utcnow().isoformat()
        }
        await publish_message_event(deletion_event, MessageTypes.MESSAGE_DELETED)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete message: {str(e)}")

@router.get("/search", response_model=List[MessageResponse])
async def search_messages(
    q: str = Query(..., min_length=3, description="Search query"),
    thread_id: Optional[str] = None,
    author: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """Search messages by content"""
    try:
        # Build search query
        search_query = {
            "content": {"$regex": q, "$options": "i"}
        }
        
        if thread_id:
            if not ObjectId.is_valid(thread_id):
                raise HTTPException(status_code=400, detail="Invalid thread ID")
            search_query["thread_id"] = thread_id
        
        if author:
            search_query["author"] = author
        
        cursor = (database.database.messages
                 .find(search_query)
                 .sort([("created_at", -1)])
                 .skip(skip)
                 .limit(limit))
        
        messages = await cursor.to_list(length=limit)
        
        return [convert_message_to_response(message) for message in messages]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search messages: {str(e)}")

@router.get("/thread/{thread_id}/replies/{message_id}", response_model=List[MessageResponse])
async def get_message_replies(
    thread_id: str,
    message_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
):
    """Get all replies to a specific message"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    if not ObjectId.is_valid(message_id):
        raise HTTPException(status_code=400, detail="Invalid message ID")
    
    try:
        # Check if thread and message exist
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        message = await database.database.messages.find_one({
            "_id": ObjectId(message_id),
            "thread_id": thread_id
        })
        if not message:
            raise HTTPException(status_code=404, detail="Message not found in this thread")
        
        # Find all replies to this message
        cursor = (database.database.messages
                 .find({
                     "thread_id": thread_id,
                     "reply_to": message_id
                 })
                 .sort([("created_at", 1)])
                 .skip(skip)
                 .limit(limit))
        
        replies = await cursor.to_list(length=limit)
        
        return [convert_message_to_response(reply) for reply in replies]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch replies: {str(e)}")
