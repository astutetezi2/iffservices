from datetime import datetime

from bson import ObjectId
from flask import Blueprint, request, jsonify

from api.routes.auth import get_current_user, db

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/getprofile", methods=["GET"])
def get_profile():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401

    user = get_current_user(auth_header)
    profile = db.member_profile.find_one({"member_id": user.get("_id")})
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(serialize_document(profile))


def serialize_document(doc):
    # Recursively convert ObjectId to string if needed
    if isinstance(doc, dict):
        return {k: serialize_document(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [serialize_document(i) for i in doc]
    elif isinstance(doc, ObjectId):
        return str(doc)
    else:
        return doc


@profile_bp.route("/follow/<followee_id>", methods=["PUT"])
def follow_user(followee_id):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    follower_user = get_current_user(auth_header)
    follower_id = follower_user.get("_id")
    if isinstance(followee_id, str):
        followee_id = ObjectId(followee_id)
    if follower_id == followee_id:
        raise ValueError("Users cannot follow themselves.")

    follower_obj_id = ObjectId(follower_id)
    followee_obj_id = ObjectId(followee_id)
    followee_user = db.members.find_one({"_id": followee_obj_id},
                                        {"name": 1, "username": 1, "full_name": 1, "avatar_url": 1})

    # Check if already following
    if db.follows.find_one({"follower_id": follower_obj_id, "followee_id": followee_obj_id}):
        print("Already following.")
        return {"success": True,
                "message": f"{follower_user['full_name']} is already following {followee_user['full_name']}"}

    # Get user details

    if not follower_user or not followee_user:
        raise ValueError("Invalid user(s).")

    # Insert follow relationship
    db.follows.insert_one({
        "follower_id": follower_obj_id,
        "followee_id": followee_obj_id,
        "followee_name": followee_user.get("full_name"),
        "followee_username": followee_user.get("username"),
        "followee_avatar": followee_user.get("avatar_url"),
        "created_at": datetime.utcnow()
    })

    # Update follower stats
    db.members.update_one(
        {"_id": followee_obj_id},
        {"$inc": {"stats.followers_count": 1}}
    )
    db.members.update_one(
        {"_id": follower_obj_id},
        {"$inc": {"stats.following_count": 1}}
    )

    return {"success": True, "message": f"{follower_user['full_name']} is now following {followee_user['full_name']}"}


@profile_bp.route("/unfollow/<followee_id>", methods=["PUT"])
def unfollow_user(followee_id):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    user = get_current_user(auth_header)
    follower_id = user.get("_id")
    follower_obj_id = ObjectId(follower_id)
    followee_obj_id = ObjectId(followee_id)
    followee_user = db.members.find_one({"_id": followee_obj_id},
                                        {"name": 1, "username": 1, "avatar_url": 1, "full_name": 1})
    # Delete follow relationship
    result = db.follows.delete_one({
        "follower_id": follower_obj_id,
        "followee_id": followee_obj_id
    })

    if result.deleted_count == 0:
        return {
            "success": True,
            "message": f"{user['full_name']} is not following {followee_user['full_name']}"
        }

    # Update stats
    db.members.update_one(
        {"_id": followee_obj_id},
        {"$inc": {"stats.followers_count": -1}}
    )

    db.members.update_one(
        {"_id": follower_obj_id},
        {"$inc": {"stats.following_count": -1}}
    )

    return {"success": True, "message": f"{user['full_name']} is now un-following {followee_user['full_name']}"}


@profile_bp.route("/iamfollowing", methods=["GET"])
def get_following_user_ids_json():
    """Return JSON list of user IDs that the logged-in user is following"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    user = get_current_user(auth_header)
    follower_id = user.get("_id")

    follows = db.follows.find(
        {"follower_id": ObjectId(follower_id)},
        {"followee_id": 1, "_id": 0}
    )

    following_ids = [str(f["followee_id"]) for f in follows]

    return jsonify({
        "status": "success",
        "following_ids": following_ids
    }), 200


def get_following_list(logged_in_user_id, limit=None):
    query = db.follows.find(
        {"follower_id": logged_in_user_id},
        {"followee_id": 1, "created_at": 1, "_id": 0}
    ).sort("created_at", -1)

    if limit:
        query = query.limit(limit)

    followees = list(query)
    followee_ids = [f["followee_id"] for f in followees]
    logged_in_following_ids = set(followee_ids)

    results = []
    for followee_id in followee_ids:
        followee_profile = db.members.find_one(
            {"_id": followee_id},
            {"full_name": 1, "onboarding.designation": 1, "avatar_url": 1}
        )

        followee_follows = db.follows.find(
            {"follower_id": followee_id},
            {"followee_id": 1, "_id": 0}
        )
        followee_following_ids = {f["followee_id"] for f in followee_follows}

        mutual_count = get_mutual_connection_count(logged_in_user_id, followee_id)

        results.append({
            "id": str(followee_id),
            "name": followee_profile.get("full_name", ""),
            "designation": followee_profile.get("onboarding", {}).get("designation", ""),
            "avatar_url": followee_profile.get("avatar_url", ""),
            "mutual_connections": mutual_count
        })

    return results


@profile_bp.route("/following/recent", methods=["GET"])
def get_recent_following():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    user = get_current_user(auth_header)
    following_list = get_following_list(user["_id"], limit=4)
    return jsonify({"success": True, "data": following_list})


@profile_bp.route("/following/list", methods=["GET"])
def get_all_following():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    user = get_current_user(auth_header)
    following_list = get_following_list(user["_id"])
    return jsonify({"success": True, "data": following_list})


@profile_bp.route("/mutual-connections/<followee_id>", methods=["GET"])
def get_mutual_connections(followee_id):
    # 1️⃣ Auth check
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Token is missing"}), 401

    user = get_current_user(auth_header)
    logged_in_user_id = ObjectId(user["_id"])
    followee_id = ObjectId(followee_id)

    # 2️⃣ Get sets of following IDs
    logged_in_following_ids = {
        f["followee_id"]
        for f in db.follows.find({"follower_id": logged_in_user_id}, {"followee_id": 1, "_id": 0})
    }

    followee_following_ids = {
        f["followee_id"]
        for f in db.follows.find({"follower_id": followee_id}, {"followee_id": 1, "_id": 0})
    }

    # 3️⃣ Intersection
    mutual_ids = list(logged_in_following_ids & followee_following_ids)

    # 4️⃣ Fetch profile details for each mutual connection
    mutual_profiles = list(
        db.members.find(
            {"_id": {"$in": mutual_ids}},
            {"full_name": 1, "onboarding.designation": 1, "avatar_url": 1}
        )
    )

    # 5️⃣ Format response
    results = [
        {
            "id": str(profile["_id"]),
            "name": profile.get("full_name", ""),
            "designation": profile.get("onboarding", {}).get("designation", ""),
            "avatar_url": profile.get("avatar_url", "")
        }
        for profile in mutual_profiles
    ]

    return jsonify({
        "status": "success",
        "count": len(results),
        "mutual_connections": results
    }), 200


@profile_bp.route("/update-settings", methods=["POST"])
def update_user_settings():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Token is missing"}), 401

    user = get_current_user(auth_header)
    user_id = user["_id"]

    data = request.get_json() or {}

    # Allowed fields & validations
    allowed_visibility = {"public", "private", "connections"}
    update_data = {}

    if "profile_visibility" in data:
        visibility = data["profile_visibility"].lower()
        if visibility not in allowed_visibility:
            return jsonify({"status": "error", "message": "Invalid profile_visibility value"}), 400
        update_data["profile_visibility"] = visibility

    if "email_notifications" in data:
        if not isinstance(data["email_notifications"], bool):
            return jsonify({"status": "error", "message": "email_notifications must be boolean"}), 400
        update_data["email_notifications"] = data["email_notifications"]

    if "direct_messages" in data:
        if not isinstance(data["direct_messages"], bool):
            return jsonify({"status": "error", "message": "direct_messages must be boolean"}), 400
        update_data["direct_messages"] = data["direct_messages"]

    if not update_data:
        return jsonify({"status": "error", "message": "No valid fields provided"}), 400

    update_data["updated_at"] = datetime.utcnow()

    # Upsert settings document for the user
    db.settings.update_one(
        {"user_id": user_id},
        {"$set": update_data},
        upsert=True
    )

    return jsonify({"status": "success", "message": "Settings updated successfully"}), 200


@profile_bp.route("/get-settings", methods=["GET"])
def get_user_settings():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Token is missing"}), 401

    user = get_current_user(auth_header)
    user_id = user["_id"]

    # Try to find the user's settings
    settings = db.settings.find_one({"user_id": user_id}, {"_id": 0, "user_id": 0})

    if not settings:
        # Defaults if the user hasn't set anything yet
        settings = {
            "profile_visibility": "public",  # default visibility
            "email_notifications": True,  # default email on
            "direct_messages": True  # default DM on
        }

    return jsonify({"status": "success", "settings": settings}), 200


def get_mutual_connection_count(logged_in_user_id, followee_id):
    """
    Returns the count of mutual connections between the logged-in user
    and the followee.
    """

    # Ensure ObjectId types
    logged_in_user_id = ObjectId(logged_in_user_id)
    followee_id = ObjectId(followee_id)

    # 1️⃣ Get the set of users the logged-in user is following
    logged_in_following_ids = {
        f["followee_id"]
        for f in db.follows.find({"follower_id": logged_in_user_id}, {"followee_id": 1, "_id": 0})
    }

    # 2️⃣ Get the set of users the followee is following
    followee_following_ids = {
        f["followee_id"]
        for f in db.follows.find({"follower_id": followee_id}, {"followee_id": 1, "_id": 0})
    }

    # 3️⃣ Intersection → mutual connections
    mutual_count = len(logged_in_following_ids & followee_following_ids)

    return mutual_count
