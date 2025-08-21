from flask import Blueprint, jsonify, request
from datetime import datetime, timezone
from pymongo import DESCENDING

from api.routes.auth import get_current_user, db
from models.database import database

activity_bp = Blueprint('activity', __name__)


@activity_bp.route('/myactivity', methods=['GET'])
def get_user_activity():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Token is missing"}), 401
    user = get_current_user(auth_header)

    limit = int(request.args.get('limit', 5))

    # Collections
    threads_col = db["threads"]
    messages_col = db["messages"]

    activities = []

    # Get recent threads by this user
    threads = list(threads_col.find(
        {"created_by._id": user["_id"]},
        {"title": 1, "community_id": 1, "created_at": 1}
    ).sort("created_at", DESCENDING).limit(limit))

    for t in threads:
        activities.append({
            "timestamp": t["created_at"],
            "description": f'Created thread "{t["title"]}"'
        })

    # Get recent messages by this user
    messages = list(messages_col.find(
        {"created_by._id": user["_id"]},
        {"thread_id": 1, "created_at": 1}
    ).sort("created_at", DESCENDING).limit(limit))

    # Map messages to threads for titles
    if messages:
        thread_ids = [m["thread_id"] for m in messages]
        thread_map = {t["_id"]: t["title"] for t in threads_col.find({"_id": {"$in": thread_ids}}, {"title": 1})}

        for m in messages:
            thread_title = thread_map.get(m["thread_id"], "a thread")
            activities.append({
                "timestamp": m["created_at"],
                "description": f"Commented on {thread_title}"
            })

    # Sort combined results
    activities = sorted(activities, key=lambda x: x["timestamp"], reverse=True)[:limit]

    # Format timestamps for readability
    for act in activities:
        act["time_ago"] = time_ago(act["timestamp"])
        del act["timestamp"]

    return jsonify({"user_id": str(user.get('_id')), "activities": activities})


def time_ago(dt):
    """Convert datetime to 'x time ago' string"""
    if dt.tzinfo is None:  # make naive datetime timezone-aware
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    diff = now - dt

    seconds = diff.total_seconds()
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if seconds < 60:
        return "just now"
    elif minutes < 60:
        return f"{int(minutes)} minute{'s' if minutes > 1 else ''} ago"
    elif hours < 24:
        return f"{int(hours)} hour{'s' if hours > 1 else ''} ago"
    else:
        return f"{int(days)} day{'s' if days > 1 else ''} ago"