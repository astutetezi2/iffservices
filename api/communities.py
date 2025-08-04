from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from models.database import database, Community
from schemas.api_schemas import (
    CreateCommunityRequest, 
    UpdateCommunityRequest, 
    CommunityResponse
)
from services.redis_broker import publish_member_event, MessageTypes

router = APIRouter(prefix="/communities", tags=["communities"])

def convert_community_to_response(community: dict) -> CommunityResponse:
    """Convert database community document to response schema"""
    community['id'] = str(community['_id'])
    del community['_id']
    return CommunityResponse(**community)

@router.get("/", response_model=List[CommunityResponse])
async def get_communities(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_public: Optional[bool] = None,
    search: Optional[str] = None
):
    """Get all communities with pagination and filtering"""
    query = {}
    
    if is_public is not None:
        query["is_public"] = is_public
    
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
            {"tags": {"$in": [search]}}
        ]
    
    try:
        cursor = database.database.communities.find(query).skip(skip).limit(limit)
        communities = await cursor.to_list(length=limit)
        
        return [convert_community_to_response(community) for community in communities]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch communities: {str(e)}")

@router.get("/{community_id}", response_model=CommunityResponse)
async def get_community(community_id: str):
    """Get a specific community by ID"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        return convert_community_to_response(community)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch community: {str(e)}")

@router.post("/", response_model=CommunityResponse, status_code=201)
async def create_community(community_data: CreateCommunityRequest, created_by: str = "user123"):  # TODO: Get from auth
    """Create a new community"""
    try:
        # Check if community name already exists
        existing = await database.database.communities.find_one({"name": community_data.name})
        if existing:
            raise HTTPException(status_code=400, detail="Community name already exists")
        
        community_dict = community_data.dict()
        community_dict["created_by"] = created_by
        community_dict["created_at"] = datetime.utcnow()
        community_dict["member_count"] = 1
        
        result = await database.database.communities.insert_one(community_dict)
        
        # Add creator to members collection if needed
        await database.database.members.update_one(
            {"username": created_by},
            {"$addToSet": {"communities": str(result.inserted_id)}},
            upsert=True
        )
        
        # Fetch the created community
        created_community = await database.database.communities.find_one({"_id": result.inserted_id})
        
        return convert_community_to_response(created_community)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create community: {str(e)}")

@router.put("/{community_id}", response_model=CommunityResponse)
async def update_community(community_id: str, community_data: UpdateCommunityRequest, user_id: str = "user123"):  # TODO: Get from auth
    """Update a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists and user has permission
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        if community["created_by"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to update this community")
        
        # Prepare update data
        update_data = {k: v for k, v in community_data.dict().items() if v is not None}
        if update_data:
            update_data["updated_at"] = datetime.utcnow()
            
            await database.database.communities.update_one(
                {"_id": ObjectId(community_id)},
                {"$set": update_data}
            )
        
        # Fetch updated community
        updated_community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        
        return convert_community_to_response(updated_community)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update community: {str(e)}")

@router.delete("/{community_id}", status_code=204)
async def delete_community(community_id: str, user_id: str = "user123"):  # TODO: Get from auth
    """Delete a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists and user has permission
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        if community["created_by"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this community")
        
        # Delete all threads in the community
        await database.database.threads.delete_many({"community_id": community_id})
        
        # Delete all messages in those threads
        await database.database.messages.delete_many({"thread_id": {"$in": []}})  # TODO: Get thread IDs first
        
        # Remove community from all members
        await database.database.members.update_many(
            {},
            {"$pull": {"communities": community_id}}
        )
        
        # Delete the community
        await database.database.communities.delete_one({"_id": ObjectId(community_id)})
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete community: {str(e)}")

@router.post("/{community_id}/join", status_code=200)
async def join_community(community_id: str, user_id: str = "user123"):  # TODO: Get from auth
    """Join a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        # Check if community is public or user has permission
        if not community.get("is_public", True):
            raise HTTPException(status_code=403, detail="Community is private")
        
        # Add user to community members
        await database.database.members.update_one(
            {"username": user_id},
            {"$addToSet": {"communities": community_id}},
            upsert=True
        )
        
        # Increment member count
        await database.database.communities.update_one(
            {"_id": ObjectId(community_id)},
            {"$inc": {"member_count": 1}}
        )
        
        # Publish member joined event
        member_data = {"user_id": user_id, "action": "joined"}
        await publish_member_event(member_data, community_id, MessageTypes.MEMBER_JOINED)
        
        return {"message": "Successfully joined community"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to join community: {str(e)}")

@router.post("/{community_id}/leave", status_code=200)
async def leave_community(community_id: str, user_id: str = "user123"):  # TODO: Get from auth
    """Leave a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        # Remove user from community members
        result = await database.database.members.update_one(
            {"username": user_id},
            {"$pull": {"communities": community_id}}
        )
        
        if result.modified_count > 0:
            # Decrement member count
            await database.database.communities.update_one(
                {"_id": ObjectId(community_id)},
                {"$inc": {"member_count": -1}}
            )
            
            # Publish member left event
            member_data = {"user_id": user_id, "action": "left"}
            await publish_member_event(member_data, community_id, MessageTypes.MEMBER_LEFT)
        
        return {"message": "Successfully left community"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to leave community: {str(e)}")

@router.get("/{community_id}/members", response_model=List[dict])
async def get_community_members(community_id: str):
    """Get all members of a community"""
    if not ObjectId.is_valid(community_id):
        raise HTTPException(status_code=400, detail="Invalid community ID")
    
    try:
        # Check if community exists
        community = await database.database.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            raise HTTPException(status_code=404, detail="Community not found")
        
        # Get all members who have this community in their communities list
        cursor = database.database.members.find({"communities": community_id})
        members = await cursor.to_list(length=None)
        
        # Convert ObjectId to string and return basic member info
        result = []
        for member in members:
            result.append({
                "id": str(member["_id"]),
                "username": member["username"],
                "full_name": member.get("full_name", ""),
                "avatar_url": member.get("avatar_url"),
                "joined_at": member.get("joined_at")
            })
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch community members: {str(e)}")
