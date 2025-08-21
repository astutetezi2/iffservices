from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest

from api.routes.auth import db, redis_client, get_current_user, members
from utils import publish_member_event  # You'd need to define this similar to FastAPI's redis broker
from schemas import validate_community_input  # define schema validations here

communities_bp = Blueprint("communities", __name__)


# def convert_community_to_response(doc):
#     doc['id'] = str(doc['_id'])
#     doc.pop('_id', None)
#     return doc


def convert_community_to_response(doc):
    community_id = str(doc["_id"])
    online_key = f"community:{community_id}:online_users"
    online_count = redis_client.scard(online_key)

    return {
        "id": community_id,
        "name": doc.get("name"),
        "members": doc.get("member_count", 0),
        "online": online_count,
        "unread": 0,  # You can add logic here
        "avatar": doc.get("avatar", "BP"),
        "color": doc.get("color", "bg-blue-600")
    }


@communities_bp.route("/list", methods=["GET"])
def get_communities():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    user = get_current_user(auth_header)

    community_ids = user["communities"]
    community_object_ids = [
        ObjectId(cid) if not isinstance(cid, ObjectId) else cid
        for cid in community_ids
    ]
    skip = int(request.args.get("skip", 0))
    limit = int(request.args.get("limit", 10))

    # 2. Fetch community details
    cursor = db.communities.find(
        {"_id": {"$in": community_object_ids}}
    ).skip(skip).limit(limit)

    return jsonify([convert_community_to_response(doc) for doc in cursor])


@communities_bp.route("/<community_id>", methods=["GET"])
def get_community(community_id):
    if not ObjectId.is_valid(community_id):
        raise BadRequest("Invalid community ID")

    doc = db.communities.find_one({"_id": ObjectId(community_id)})
    if not doc:
        return jsonify({"error": "Community not found"}), 404
    return jsonify(convert_community_to_response(doc))


@communities_bp.route("/", methods=["POST"])
def create_community():
    data = request.get_json()
    validate_community_input(data)

    existing = db.communities.find_one({"name": data["name"]})
    if existing:
        return jsonify({"error": "Community already exists"}), 400

    data.update({
        "created_by": "user123",  # Replace with real user ID from auth
        "created_at": datetime.utcnow(),
        "member_count": 1
    })
    result = db.communities.insert_one(data)

    db.members.update_one(
        {"username": "user123"},
        {"$addToSet": {"communities": str(result.inserted_id)}},
        upsert=True
    )

    new_doc = db.communities.find_one({"_id": result.inserted_id})
    return jsonify(convert_community_to_response(new_doc)), 201


@communities_bp.route("/<community_id>", methods=["PUT"])
def update_community(community_id):
    data = request.get_json()
    if not ObjectId.is_valid(community_id):
        raise BadRequest("Invalid community ID")

    community = db.communities.find_one({"_id": ObjectId(community_id)})
    if not community:
        return jsonify({"error": "Community not found"}), 404

    if community["created_by"] != "user123":
        return jsonify({"error": "Not authorized"}), 403

    update_data = {k: v for k, v in data.items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()

    db.communities.update_one({"_id": ObjectId(community_id)}, {"$set": update_data})
    updated = db.communities.find_one({"_id": ObjectId(community_id)})
    return jsonify(convert_community_to_response(updated))


@communities_bp.route("/<community_id>", methods=["DELETE"])
def delete_community(community_id):
    if not ObjectId.is_valid(community_id):
        raise BadRequest("Invalid community ID")

    community = db.communities.find_one({"_id": ObjectId(community_id)})
    if not community:
        return jsonify({"error": "Community not found"}), 404

    if community["created_by"] != "user123":
        return jsonify({"error": "Not authorized"}), 403

    db.threads.delete_many({"community_id": community_id})
    db.messages.delete_many({"thread_id": {"$in": []}})  # TODO: Fetch thread IDs
    db.members.update_many({}, {"$pull": {"communities": community_id}})
    db.communities.delete_one({"_id": ObjectId(community_id)})
    return "", 204


@communities_bp.route("/<community_id>/join", methods=["POST"])
def join_community(community_id):
    if not ObjectId.is_valid(community_id):
        raise BadRequest("Invalid community ID")

    community = db.communities.find_one({"_id": ObjectId(community_id)})
    if not community:
        return jsonify({"error": "Not found"}), 404

    if not community.get("is_public", True):
        return jsonify({"error": "Private community"}), 403

    db.members.update_one(
        {"username": "user123"},
        {"$addToSet": {"communities": community_id}},
        upsert=True
    )
    db.communities.update_one({"_id": ObjectId(community_id)}, {"$inc": {"member_count": 1}})

    publish_member_event({"user_id": "user123", "action": "joined"}, community_id, "MEMBER_JOINED")
    return jsonify({"message": "Successfully joined"})


@communities_bp.route("/<community_id>/leave", methods=["POST"])
def leave_community(community_id):
    if not ObjectId.is_valid(community_id):
        raise BadRequest("Invalid community ID")

    community = db.communities.find_one({"_id": ObjectId(community_id)})
    if not community:
        return jsonify({"error": "Not found"}), 404

    result = db.members.update_one(
        {"username": "user123"},
        {"$pull": {"communities": community_id}}
    )

    if result.modified_count > 0:
        db.communities.update_one({"_id": ObjectId(community_id)}, {"$inc": {"member_count": -1}})
        publish_member_event({"user_id": "user123", "action": "left"}, community_id, "MEMBER_LEFT")

    return jsonify({"message": "Successfully left"})


@communities_bp.route("/<community_id>/members", methods=["GET"])
def get_members(community_id):
    if not ObjectId.is_valid(community_id):
        raise BadRequest("Invalid community ID")

    community = db.communities.find_one({"_id": ObjectId(community_id)})
    if not community:
        return jsonify({"error": "Not found"}), 404

    members = db.members.find({"communities": community_id})
    result = []
    for m in members:
        result.append({
            "id": str(m["_id"]),
            "username": m["username"],
            "full_name": m.get("full_name", ""),
            "avatar_url": m.get("avatar_url"),
            "joined_at": m.get("joined_at")
        })

    return jsonify(result)
