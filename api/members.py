from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from models.database import database, Member
from schemas.api_schemas import CreateMemberRequest, MemberResponse

router = APIRouter(prefix="/members", tags=["members"])

def convert_member_to_response(member: dict) -> MemberResponse:
    """Convert database member document to response schema"""
    member['id'] = str(member['_id'])
    del member['_id']
    return MemberResponse(**member)

@router.get("/", response_model=List[MemberResponse])
async def get_members(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None
):
    """Get all members with pagination and filtering"""
    query = {}
    
    if is_active is not None:
        query["is_active"] = is_active
    
    if search:
        query["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]
    
    try:
        cursor = database.database.members.find(query).skip(skip).limit(limit)
        members = await cursor.to_list(length=limit)
        
        return [convert_member_to_response(member) for member in members]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch members: {str(e)}")

@router.get("/{member_id}", response_model=MemberResponse)
async def get_member(member_id: str):
    """Get a specific member by ID"""
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member ID")
    
    try:
        member = await database.database.members.find_one({"_id": ObjectId(member_id)})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        return convert_member_to_response(member)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch member: {str(e)}")

@router.get("/username/{username}", response_model=MemberResponse)
async def get_member_by_username(username: str):
    """Get a specific member by username"""
    try:
        member = await database.database.members.find_one({"username": username})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        return convert_member_to_response(member)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch member: {str(e)}")

@router.post("/", response_model=MemberResponse, status_code=201)
async def create_member(member_data: CreateMemberRequest):
    """Create a new member"""
    try:
        # Check if username already exists
        existing_username = await database.database.members.find_one({"username": member_data.username})
        if existing_username:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Check if email already exists
        existing_email = await database.database.members.find_one({"email": member_data.email})
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")
        
        member_dict = member_data.dict()
        member_dict["joined_at"] = datetime.utcnow()
        member_dict["is_active"] = True
        member_dict["communities"] = []
        
        result = await database.database.members.insert_one(member_dict)
        
        # Fetch the created member
        created_member = await database.database.members.find_one({"_id": result.inserted_id})
        
        return convert_member_to_response(created_member)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create member: {str(e)}")

@router.put("/{member_id}", response_model=MemberResponse)
async def update_member(member_id: str, member_data: CreateMemberRequest, current_user: str = "user123"):  # TODO: Get from auth
    """Update member profile"""
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member ID")
    
    try:
        # Check if member exists
        member = await database.database.members.find_one({"_id": ObjectId(member_id)})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        # Check if current user can update this profile
        if member["username"] != current_user:
            raise HTTPException(status_code=403, detail="Not authorized to update this profile")
        
        # Check if new username already exists (if different)
        if member_data.username != member["username"]:
            existing_username = await database.database.members.find_one({"username": member_data.username})
            if existing_username:
                raise HTTPException(status_code=400, detail="Username already exists")
        
        # Check if new email already exists (if different)
        if member_data.email != member["email"]:
            existing_email = await database.database.members.find_one({"email": member_data.email})
            if existing_email:
                raise HTTPException(status_code=400, detail="Email already exists")
        
        # Update member
        update_data = member_data.dict()
        
        await database.database.members.update_one(
            {"_id": ObjectId(member_id)},
            {"$set": update_data}
        )
        
        # Fetch updated member
        updated_member = await database.database.members.find_one({"_id": ObjectId(member_id)})
        
        return convert_member_to_response(updated_member)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update member: {str(e)}")

@router.delete("/{member_id}", status_code=204)
async def delete_member(member_id: str, current_user: str = "user123"):  # TODO: Get from auth
    """Delete/deactivate member account"""
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member ID")
    
    try:
        # Check if member exists
        member = await database.database.members.find_one({"_id": ObjectId(member_id)})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        # Check if current user can delete this profile
        if member["username"] != current_user:
            raise HTTPException(status_code=403, detail="Not authorized to delete this profile")
        
        # Instead of deleting, mark as inactive (soft delete)
        await database.database.members.update_one(
            {"_id": ObjectId(member_id)},
            {"$set": {"is_active": False}}
        )
        
        # Remove from all communities
        await database.database.communities.update_many(
            {},
            {"$pull": {"members": member_id}, "$inc": {"member_count": -1}}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete member: {str(e)}")

@router.get("/{member_id}/communities", response_model=List[dict])
async def get_member_communities(member_id: str):
    """Get all communities a member belongs to"""
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member ID")
    
    try:
        # Check if member exists
        member = await database.database.members.find_one({"_id": ObjectId(member_id)})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        # Get communities
        community_ids = [ObjectId(cid) for cid in member.get("communities", []) if ObjectId.is_valid(cid)]
        
        if not community_ids:
            return []
        
        cursor = database.database.communities.find({"_id": {"$in": community_ids}})
        communities = await cursor.to_list(length=None)
        
        # Convert ObjectId to string
        result = []
        for community in communities:
            result.append({
                "id": str(community["_id"]),
                "name": community["name"],
                "description": community["description"],
                "member_count": community.get("member_count", 0),
                "is_public": community.get("is_public", True),
                "avatar_url": community.get("avatar_url")
            })
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch member communities: {str(e)}")

@router.get("/{member_id}/activity", response_model=dict)
async def get_member_activity(
    member_id: str,
    days: int = Query(30, ge=1, le=365, description="Number of days to look back")
):
    """Get member activity statistics"""
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member ID")
    
    try:
        # Check if member exists
        member = await database.database.members.find_one({"_id": ObjectId(member_id)})
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        
        username = member["username"]
        
        # Calculate date range
        from_date = datetime.utcnow() - timedelta(days=days)
        
        # Count threads created
        thread_count = await database.database.threads.count_documents({
            "created_by": username,
            "created_at": {"$gte": from_date}
        })
        
        # Count messages posted
        message_count = await database.database.messages.count_documents({
            "author": username,
            "created_at": {"$gte": from_date}
        })
        
        # Get communities joined
        communities_count = len(member.get("communities", []))
        
        return {
            "member_id": member_id,
            "username": username,
            "period_days": days,
            "threads_created": thread_count,
            "messages_posted": message_count,
            "communities_joined": communities_count,
            "activity_score": thread_count * 5 + message_count  # Simple scoring system
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch member activity: {str(e)}")

# Import timedelta for activity endpoint
from datetime import timedelta
