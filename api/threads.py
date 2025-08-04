from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from models.database import database, Thread
from schemas.api_schemas import (
    CreateThreadRequest, 
    UpdateThreadRequest, 
    ThreadResponse
)
from services.redis_broker import publish_thread_event, MessageTypes

router = APIRouter(prefix="/threads", tags=["threads"])

def convert_thread_to_response(thread: dict) -> ThreadResponse:
    """Convert database thread document to response schema"""
    thread['id'] = str(thread['_id'])
    del thread['_id']
    return ThreadResponse(**thread)

@router.get("/community/{community_id}", response_model=List[ThreadResponse])
async def get_community_threads(
    community_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("last_activity", regex="^(created_at|last_activity|message_count)$")
):
    """Get all threads in a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        # Build sort criteria
        sort_order = -1 if sort_by in ["last_activity", "created_at"] else -1
        sort_criteria = [(sort_by, sort_order)]
        
        # Add secondary sort by is_pinned (pinned threads first)
        if sort_by != "is_pinned":
            sort_criteria.insert(0, ("is_pinned", -1))
        
        cursor = (database.database.threads
                 .find({"community_id": community_id})
                 .sort(sort_criteria)
                 .skip(skip)
                 .limit(limit))
        
        threads = await cursor.to_list(length=limit)
        
        return [convert_thread_to_response(thread) for thread in threads]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch threads: {str(e)}")

@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(thread_id: str):
    """Get a specific thread by ID"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    
    try:
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        return convert_thread_to_response(thread)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch thread: {str(e)}")

@router.post("/community/{community_id}", response_model=ThreadResponse, status_code=201)
async def create_thread(
    community_id: str, 
    thread_data: CreateThreadRequest, 
    created_by: str = "user123"  # TODO: Get from auth
):
    """Create a new thread in a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        # Check if user is a member of the community
        member = await database.database.members.find_one({
            "username": created_by,
            "communities": community_id
        })
        if not member:
            raise HTTPException(status_code=403, detail="You must be a member of the community to create threads")
        
        thread_dict = thread_data.dict()
        thread_dict["community_id"] = community_id
        thread_dict["created_by"] = created_by
        thread_dict["created_at"] = datetime.utcnow()
        thread_dict["updated_at"] = datetime.utcnow()
        thread_dict["last_activity"] = datetime.utcnow()
        thread_dict["message_count"] = 0
        thread_dict["is_pinned"] = False
        
        result = await database.database.threads.insert_one(thread_dict)
        
        # Fetch the created thread
        created_thread = await database.database.threads.find_one({"_id": result.inserted_id})
        
        # Publish thread creation event
        thread_response = convert_thread_to_response(created_thread.copy())
        await publish_thread_event(thread_response.dict(), MessageTypes.NEW_THREAD)
        
        return thread_response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create thread: {str(e)}")

@router.put("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str, 
    thread_data: UpdateThreadRequest, 
    user_id: str = "user123"  # TODO: Get from auth
):
    """Update a thread"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    
    try:
        # Check if thread exists and user has permission
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        if thread["created_by"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to update this thread")
        
        # Prepare update data
        update_data = {k: v for k, v in thread_data.dict().items() if v is not None}
        if update_data:
            update_data["updated_at"] = datetime.utcnow()
            
            await database.database.threads.update_one(
                {"_id": ObjectId(thread_id)},
                {"$set": update_data}
            )
        
        # Fetch updated thread
        updated_thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        thread_response = convert_thread_to_response(updated_thread)
        
        # Publish thread update event
        await publish_thread_event(thread_response.dict(), MessageTypes.THREAD_UPDATED)
        
        return thread_response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update thread: {str(e)}")

@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, user_id: str = "user123"):  # TODO: Get from auth
    """Delete a thread"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    
    try:
        # Check if thread exists and user has permission
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        # Check permission (thread creator or community admin)
        if thread["created_by"] != user_id:
            # Check if user is community admin
            community = await database.database.communities.find_one({"_id": ObjectId(thread["community_id"])})
            if not community or community["created_by"] != user_id:
                raise HTTPException(status_code=403, detail="Not authorized to delete this thread")
        
        # Delete all messages in the thread
        await database.database.messages.delete_many({"thread_id": thread_id})
        
        # Delete the thread
        await database.database.threads.delete_one({"_id": ObjectId(thread_id)})
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete thread: {str(e)}")

@router.post("/{thread_id}/pin", status_code=200)
async def pin_thread(thread_id: str, user_id: str = "user123"):  # TODO: Get from auth
    """Pin or unpin a thread"""
    if not ObjectId.is_valid(thread_id):
        raise HTTPException(status_code=400, detail="Invalid thread ID")
    
    try:
        # Check if thread exists
        thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        # Check if user is community admin
        community = await database.database.communities.find_one({"_id": ObjectId(thread["community_id"])})
        if not community or community["created_by"] != user_id:
            raise HTTPException(status_code=403, detail="Only community admins can pin threads")
        
        # Toggle pin status
        new_pin_status = not thread.get("is_pinned", False)
        
        await database.database.threads.update_one(
            {"_id": ObjectId(thread_id)},
            {"$set": {"is_pinned": new_pin_status, "updated_at": datetime.utcnow()}}
        )
        
        # Fetch updated thread
        updated_thread = await database.database.threads.find_one({"_id": ObjectId(thread_id)})
        thread_response = convert_thread_to_response(updated_thread)
        
        # Publish thread update event
        await publish_thread_event(thread_response.dict(), MessageTypes.THREAD_UPDATED)
        
        action = "pinned" if new_pin_status else "unpinned"
        return {"message": f"Thread {action} successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to pin/unpin thread: {str(e)}")

@router.get("/search", response_model=List[ThreadResponse])
async def search_threads(
    q: str = Query(..., min_length=3, description="Search query"),
    community_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
):
    """Search threads by title and content"""
    try:
        # Build search query
        search_query = {
            "$or": [
                {"title": {"$regex": q, "$options": "i"}},
                {"content": {"$regex": q, "$options": "i"}},
                {"tags": {"$in": [q]}}
            ]
        }
        
        if community_id:
            if not ObjectId.is_valid(community_id):
                raise HTTPException(status_code=400, detail="Invalid community ID")
            search_query["community_id"] = community_id
        
        cursor = (database.database.threads
                 .find(search_query)
                 .sort([("last_activity", -1)])
                 .skip(skip)
                 .limit(limit))
        
        threads = await cursor.to_list(length=limit)
        
        return [convert_thread_to_response(thread) for thread in threads]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search threads: {str(e)}")
