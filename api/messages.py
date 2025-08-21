from flask import Blueprint, request, jsonify
from bson import ObjectId
from datetime import datetime
from pymongo import DESCENDING, ASCENDING

from api.routes.auth import db, get_current_user
from models.database import database
from services.redis_broker import publish_message_event, MessageTypes
from utils import upload_file

messages_bp = Blueprint("messages", __name__)
ALLOWED_EXTENSIONS = {"pdf", "jpeg", "jpg"}


def convert_message_to_response(msg, thread_author_id, all_messages_dict, current_user_id):
    if isinstance(msg.get("created_by"), dict):
        author_name = msg["created_by"].get("full_name", "Admin")
    else:
        author_name = "Admin"
    avatar = "".join([part[0] for part in author_name.split()]).upper()

    # Determine if current user liked this message
    is_liked = False
    if current_user_id and isinstance(msg.get("liked_by"), list):
        is_liked = any(
            like.get("user_id") == str(current_user_id) for like in msg["liked_by"]
        )

    return {
        "id": str(msg["_id"]),
        "user_id": str(msg.get("created_by")["_id"]),
        "author": author_name,
        "avatar": avatar,
        "content": msg.get("content", ""),
        "attachments": msg.get("attachments"),
        "timestamp": humanize_time(msg.get("created_at")),
        "isOP": (msg.get("author_id") == thread_author_id),
        "is_liked": is_liked,
        "likes": msg.get("likes", 0),
        "replies": [
            convert_message_to_response(child, thread_author_id, all_messages_dict, current_user_id)
            for child in all_messages_dict.get(str(msg["_id"]), [])
        ]
    }


def convert_message(message):
    message['id'] = str(message['_id'])
    del message['_id']
    return message


def humanize_time(dt):
    if not dt:
        return ""
    diff = datetime.utcnow() - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    elif seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    else:
        return f"{int(seconds // 86400)} days ago"


@messages_bp.route("/get_thread_messages/<thread_id>", methods=["GET"])
def get_thread_messages(thread_id):
    if not ObjectId.is_valid(thread_id):
        return jsonify({"error": "Invalid thread ID"}), 400

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401

    user = get_current_user(auth_header)

    skip = int(request.args.get("skip", 0))
    limit = int(request.args.get("limit", 50))
    sort_order = request.args.get("sort_order", "asc")
    sort_dir = ASCENDING if sort_order == "asc" else DESCENDING

    thread = db.threads.find_one({"_id": ObjectId(thread_id)})
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    thread_author_id = thread.get("created_by")  # Might be ObjectId

    # Fetch all messages for thread
    messages_cursor = db.messages.find({"thread_id": thread_id}).sort("created_at", sort_dir)
    messages_list = list(messages_cursor)

    # Organize messages by parent_id
    all_messages_dict = {}
    root_messages = []
    for m in messages_list:
        parent_id = m.get("reply_to")
        if parent_id:
            all_messages_dict.setdefault(str(parent_id), []).append(m)
        else:
            root_messages.append(m)

    # Build response tree
    response = [
        convert_message_to_response(msg, thread_author_id, all_messages_dict, user.get('_id'))
        for msg in root_messages
    ]

    return jsonify(response)


@messages_bp.route("/<message_id>", methods=["GET"])
def get_message(message_id):
    if not ObjectId.is_valid(message_id):
        return jsonify({"error": "Invalid message ID"}), 400

    message = database.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        return jsonify({"error": "Message not found"}), 404
    return jsonify(convert_message(message))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
@messages_bp.route("/create/<thread_id>", methods=["POST"])
def create_message(thread_id):
    global ext, thumbnail_url, file_url
    if not ObjectId.is_valid(thread_id):
        return jsonify({"error": "Invalid thread ID"}), 400

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    data = {}
    attachments_meta = []
    user = get_current_user(auth_header)
    if request.content_type.startswith("multipart/form-data"):
        if not request.form.get("content") and not request.files.getlist("attachments"):
            return jsonify({"error": "Message must have either content or attachments"}), 400
        data["content"] = request.form.get("content")
        data["reply_to"] = request.form.get("reply_to")
        files = request.files.getlist("attachments")
        for f in files:
            try:
                file_url, thumb_url, ext = upload_file(f)
                attachments_meta.append({
                    "filename": f.filename,
                    "file_url": file_url,
                    "thumbnail_url": thumb_url,
                    "type": ext
                })
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
    elif request.is_json:
        if not data.get("content") and not data.get("attachments"):
            return jsonify({"error": "Message must have either content or attachments"}), 400
        data = request.get_json()

    # Ensure content or attachments are present



    # Validate thread exists
    thread = db.threads.find_one({"_id": ObjectId(thread_id)})
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    # Validate reply_to if provided
    if data.get("reply_to"):
        if not ObjectId.is_valid(data["reply_to"]):
            return jsonify({"error": "Invalid reply_to message ID"}), 400
        reply = db.messages.find_one({"_id": ObjectId(data["reply_to"]), "thread_id": thread_id})
        if not reply:
            return jsonify({"error": "Reply target not found in thread"}), 404

    # Build message object
    message = {
        "thread_id": thread_id,
        "created_by": user,  # storing full user object snapshot
        "content": data.get("content", ""),
        "attachments": attachments_meta,
        "reply_to": ObjectId(data["reply_to"]) if data.get("reply_to") else None,
        "created_at": datetime.utcnow(),
        "is_edited": False,
        "likes": 0  # default likes count
    }

    # Insert message
    result = db.messages.insert_one(message)

    # Update thread activity
    db.threads.update_one(
        {"_id": ObjectId(thread_id)},
        {
            "$inc": {"message_count": 1},
            "$set": {"last_activity": datetime.utcnow()}
        }
    )

    # Fetch newly created message
    created = db.messages.find_one({"_id": result.inserted_id})

    # Convert to response format
    msg_resp = convert_message_to_response(created, str(thread["created_by"]["_id"]), {}, user.get('_id'))
    publish_message_event(msg_resp, MessageTypes.NEW_MESSAGE)

    return get_thread_messages(thread_id)
    # return jsonify(msg_resp), 201


@messages_bp.route("/message/like/<message_id>", methods=["POST"])
def like_message(message_id):
    if not ObjectId.is_valid(message_id):
        return jsonify({"status": "error", "message": "Invalid message ID"}), 400

        # Get current user
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Token is missing"}), 401
    user = get_current_user(auth_header)

    # Build user object
    user_obj = {
        "user_id": str(user["_id"]),
        "full_name": user.get("full_name", "Anonymous")
    }
    message = db.messages.find_one({"_id": ObjectId(message_id)})

    if not message:
        return jsonify({"status": "error", "message": "Message not found"}), 404

    # Now, check if the logged-in user has liked this message
    user_liked = any(like.get("user_id") == user_obj["user_id"] for like in message.get("liked_by", []))

    if user_liked:
        # User already liked → remove (dislike)
        result = db.messages.update_one(
            {"_id": ObjectId(message_id)},
            {"$pull": {"liked_by": {"user_id": user_obj["user_id"]}}}
        )
        action = "disliked"

        # Decrease likes_count on thread
        db.threads.update_one(
            {"_id": ObjectId(message.get('thread_id'))},
            {
                "$inc": {"likes_count": -1},
                "$set": {"last_activity": datetime.utcnow()}
            }
        )
    else:
        # User has not liked → add
        result = db.messages.update_one(
            {"_id": ObjectId(message_id)},
            {"$push": {"liked_by": user_obj}}
        )
        action = "liked"

        # Increase likes_count on thread
        db.threads.update_one(
            {"_id": ObjectId(message.get('thread_id'))},
            {
                "$inc": {"likes_count": 1},
                "$set": {"last_activity": datetime.utcnow()}
            }
        )

    if result.modified_count > 0:
        return jsonify({
            "status": "success",
            "message": f"Message {message_id} {action} successfully."
        }), 200
    else:
        return jsonify({
            "status": "error",
            "message": f"No message found with ID {message_id}."
        }), 404

@messages_bp.route("/<message_id>", methods=["PUT"])
def update_message(message_id):
    if not ObjectId.is_valid(message_id):
        return jsonify({"error": "Invalid message ID"}), 400

    data = request.json
    user_id = data.get("author", "user123")

    message = database.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        return jsonify({"error": "Message not found"}), 404

    if message["author"] != user_id:
        return jsonify({"error": "Not authorized"}), 403

    update = {
        "content": data["content"],
        "edited_at": datetime.utcnow(),
        "is_edited": True
    }

    database.messages.update_one({"_id": ObjectId(message_id)}, {"$set": update})
    updated = database.messages.find_one({"_id": ObjectId(message_id)})
    msg_resp = convert_message_to_response(updated)
    publish_message_event(msg_resp, MessageTypes.MESSAGE_UPDATED)
    return jsonify(msg_resp)


@messages_bp.route("/<message_id>", methods=["DELETE"])
def delete_message(message_id):
    if not ObjectId.is_valid(message_id):
        return jsonify({"error": "Invalid message ID"}), 400

    user_id = request.args.get("user_id", "user123")
    message = database.messages.find_one({"_id": ObjectId(message_id)})
    if not message:
        return "", 204

    thread = database.threads.find_one({"_id": ObjectId(message["thread_id"])})
    community = database.communities.find_one({"_id": ObjectId(thread["community_id"])})

    if message["author"] != user_id and (not community or community["created_by"] != user_id):
        return jsonify({"error": "Not authorized"}), 403

    database.messages.delete_one({"_id": ObjectId(message_id)})
    database.threads.update_one({"_id": ObjectId(message["thread_id"])}, {"$inc": {"message_count": -1}})

    deletion_event = {
        "id": message_id,
        "thread_id": message["thread_id"],
        "deleted_by": user_id,
        "deleted_at": datetime.utcnow().isoformat()
    }
    publish_message_event(deletion_event, MessageTypes.MESSAGE_DELETED)
    return "", 204


@messages_bp.route("/search", methods=["GET"])
def search_messages():
    q = request.args.get("q")
    if not q or len(q) < 3:
        return jsonify({"error": "Search query too short"}), 400

    thread_id = request.args.get("thread_id")
    author = request.args.get("author")
    skip = int(request.args.get("skip", 0))
    limit = int(request.args.get("limit", 50))

    search_query = {"content": {"$regex": q, "$options": "i"}}
    if thread_id:
        if not ObjectId.is_valid(thread_id):
            return jsonify({"error": "Invalid thread ID"}), 400
        search_query["thread_id"] = thread_id
    if author:
        search_query["author"] = author

    cursor = (database.messages.find(search_query)
              .sort("created_at", DESCENDING)
              .skip(skip)
              .limit(limit))
    messages = list(cursor)
    return jsonify([convert_message_to_response(m) for m in messages])


@messages_bp.route("/thread/<thread_id>/replies/<message_id>", methods=["GET"])
def get_message_replies(thread_id, message_id):
    if not ObjectId.is_valid(thread_id) or not ObjectId.is_valid(message_id):
        return jsonify({"error": "Invalid ID"}), 400

    skip = int(request.args.get("skip", 0))
    limit = int(request.args.get("limit", 20))

    thread = database.threads.find_one({"_id": ObjectId(thread_id)})
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    message = database.messages.find_one({"_id": ObjectId(message_id), "thread_id": thread_id})
    if not message:
        return jsonify({"error": "Message not found in thread"}), 404

    replies = database.messages.find({"thread_id": thread_id, "reply_to": message_id}) \
        .sort("created_at", ASCENDING) \
        .skip(skip) \
        .limit(limit)

    return jsonify([convert_message_to_response(r) for r in replies])
