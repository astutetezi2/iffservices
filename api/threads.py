import asyncio

from flask import Blueprint, request, jsonify
from bson import ObjectId
from datetime import datetime

from flask_jwt_extended import jwt_required

from api.routes.auth import db, get_current_user
from models.database import database
from services.redis_broker import publish_thread_event, MessageTypes

threads_bp = Blueprint("threads", __name__)


# def convert_thread_to_response(thread):
#     thread['id'] = str(thread['_id'])
#     del thread['_id']
#     return thread

def humanize_time(dt):
    if not isinstance(dt, datetime):
        return ""
    diff = datetime.utcnow() - dt
    if diff.days > 0:
        return f"{diff.days} days ago"
    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours} hours ago"
    minutes = diff.seconds // 60
    return f"{minutes} minutes ago"


def convert_thread_to_response(thread_doc, community_id):
    author_name = thread_doc["created_by"]["full_name"]
    designation = thread_doc["created_by"]["onboarding"]["designation"]
    company = thread_doc["created_by"]["onboarding"]["company"]
    bio = thread_doc["created_by"]["onboarding"]["bio"]
    reputation = thread_doc["created_by"]["stats"]["reputation"]
    posts = thread_doc["created_by"]["stats"]["posts"]
    avatar = "".join([part[0].upper() for part in author_name.split()]) if author_name else ""
    is_active = thread_doc.get("is_active", False)
    user_id = thread_doc["created_by"]["_id"]

    return {
        "community_id": community_id,
        "id": str(thread_doc["_id"]),
        "author": author_name,
        "avatar": avatar,
        "content": thread_doc.get("content", ""),
        "timestamp": humanize_time(thread_doc.get("created_at")),
        "replies": thread_doc.get("message_count", 0),
        "likes": thread_doc.get("likes_count", 0),
        "isActive": is_active,
        "isPinned": thread_doc.get("is_pinned", False),
        "type": "post",
        "designation": designation,
        "company": company,
        "bio": bio,
        "reputation": reputation,
        "posts": posts,
        "user_id": str(user_id)
    }


@threads_bp.route("/get_threads/<community_id>", methods=["GET"])
@jwt_required()
def get_community_threads(community_id):
    if not ObjectId.is_valid(community_id):
        return jsonify({"error": "Invalid community ID"}), 400

    try:
        community = db.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            return jsonify({"error": "Community not found"}), 404

        skip = int(request.args.get("skip", 0))
        limit = int(request.args.get("limit", 20))
        sort_by = request.args.get("sort_by", "last_activity")
        sort_criteria = [("is_pinned", -1), (sort_by, -1)]

        cursor = (db.threads
                  .find({"community_id": community_id})
                  .sort(sort_criteria)
                  .skip(skip)
                  .limit(limit))

        threads = list(cursor)
        return jsonify([convert_thread_to_response(thread, community_id) for thread in threads])
    except Exception as e:
        return jsonify({"error": f"Failed to fetch threads: {str(e)}"}), 500


@threads_bp.route("/<thread_id>", methods=["GET"])
def get_thread(thread_id):
    if not ObjectId.is_valid(thread_id):
        return jsonify({"error": "Invalid thread ID"}), 400

    try:
        thread = db.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            return jsonify({"error": "Thread not found"}), 404

        return jsonify(convert_thread_to_response(thread, thread['community_id']))
    except Exception as e:
        return jsonify({"error": f"Failed to fetch thread: {str(e)}"}), 500


@threads_bp.route("/community/<community_id>", methods=["POST"])
@jwt_required()
def create_thread(community_id):
    if not ObjectId.is_valid(community_id):
        return jsonify({"error": "Invalid community ID"}), 400
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    user = get_current_user(auth_header)

    data = request.get_json()
    title = data.get('title')
    content = data.get('content')

    try:
        community = db.communities.find_one({"_id": ObjectId(community_id)})
        if not community:
            return jsonify({"error": "Community not found"}), 404

        if str(community_id) not in [str(c_id) for c_id in user.get("communities", [])]:
            return jsonify({"error": "You are not part of this community"}), 403

        thread_dict = {
            "community_id": community_id,
            "created_by": user,
            "title": title,
            "content": content,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "message_count": 0,
            "is_pinned": False,
            **data
        }

        result = db.threads.insert_one(thread_dict)
        db.threads.create_index("created_by")
        thread = db.threads.find_one({"_id": result.inserted_id})
        thread_response = convert_thread_to_response(thread, community_id)
        publish_thread_event(thread_response, MessageTypes.NEW_THREAD)
        return jsonify(thread_response), 201
    except Exception as e:
        return jsonify({"error": f"Failed to create thread: {str(e)}"}), 500


@threads_bp.route("/<thread_id>", methods=["PUT"])
def update_thread(thread_id):
    if not ObjectId.is_valid(thread_id):
        return jsonify({"error": "Invalid thread ID"}), 400

    data = request.get_json()
    user_id = request.headers.get("X-User", "user123")

    try:
        thread = database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            return jsonify({"error": "Thread not found"}), 404

        if thread["created_by"] != user_id:
            return jsonify({"error": "Not authorized"}), 403

        update_data = {k: v for k, v in data.items() if v is not None}
        update_data["updated_at"] = datetime.utcnow()

        database.database.threads.update_one(
            {"_id": ObjectId(thread_id)},
            {"$set": update_data}
        )

        updated_thread = database.database.threads.find_one({"_id": ObjectId(thread_id)})
        thread_response = convert_thread_to_response(updated_thread)
        publish_thread_event(thread_response, MessageTypes.THREAD_UPDATED)
        return jsonify(thread_response)
    except Exception as e:
        return jsonify({"error": f"Failed to update thread: {str(e)}"}), 500


@threads_bp.route("/<thread_id>", methods=["DELETE"])
def delete_thread(thread_id):
    if not ObjectId.is_valid(thread_id):
        return jsonify({"error": "Invalid thread ID"}), 400

    user_id = request.headers.get("X-User", "user123")

    try:
        thread = database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            return jsonify({"error": "Thread not found"}), 404

        community = database.database.communities.find_one({"_id": ObjectId(thread["community_id"])})
        if thread["created_by"] != user_id and (not community or community["created_by"] != user_id):
            return jsonify({"error": "Not authorized"}), 403

        database.database.messages.delete_many({"thread_id": thread_id})
        database.database.threads.delete_one({"_id": ObjectId(thread_id)})
        return "", 204
    except Exception as e:
        return jsonify({"error": f"Failed to delete thread: {str(e)}"}), 500


@threads_bp.route("/<thread_id>/pin", methods=["POST"])
def pin_thread(thread_id):
    if not ObjectId.is_valid(thread_id):
        return jsonify({"error": "Invalid thread ID"}), 400

    user_id = request.headers.get("X-User", "user123")

    try:
        thread = database.database.threads.find_one({"_id": ObjectId(thread_id)})
        if not thread:
            return jsonify({"error": "Thread not found"}), 404

        community = database.database.communities.find_one({"_id": ObjectId(thread["community_id"])})
        if not community or community["created_by"] != user_id:
            return jsonify({"error": "Only community admins can pin threads"}), 403

        new_pin_status = not thread.get("is_pinned", False)

        database.database.threads.update_one(
            {"_id": ObjectId(thread_id)},
            {"$set": {"is_pinned": new_pin_status, "updated_at": datetime.utcnow()}}
        )

        updated_thread = database.database.threads.find_one({"_id": ObjectId(thread_id)})
        thread_response = convert_thread_to_response(updated_thread)
        publish_thread_event(thread_response, MessageTypes.THREAD_UPDATED)

        action = "pinned" if new_pin_status else "unpinned"
        return jsonify({"message": f"Thread {action} successfully"})
    except Exception as e:
        return jsonify({"error": f"Failed to pin/unpin thread: {str(e)}"}), 500


@threads_bp.route("/search", methods=["GET"])
def search_threads():
    q = request.args.get("q")
    community_id = request.args.get("community_id")
    skip = int(request.args.get("skip", 0))
    limit = int(request.args.get("limit", 20))

    if not q or len(q) < 3:
        return jsonify({"error": "Query must be at least 3 characters"}), 400

    try:
        search_query = {
            "$or": [
                {"title": {"$regex": q, "$options": "i"}},
                {"content": {"$regex": q, "$options": "i"}},
                {"tags": {"$in": [q]}}
            ]
        }

        if community_id:
            if not ObjectId.is_valid(community_id):
                return jsonify({"error": "Invalid community ID"}), 400
            search_query["community_id"] = community_id

        cursor = (database.database.threads
                  .find(search_query)
                  .sort("last_activity", -1)
                  .skip(skip)
                  .limit(limit))

        threads = list(cursor)
        return jsonify([convert_thread_to_response(thread) for thread in threads])
    except Exception as e:
        return jsonify({"error": f"Failed to search threads: {str(e)}"}), 500
