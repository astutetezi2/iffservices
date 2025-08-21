from flask import Blueprint, request, jsonify
from bson import ObjectId
from datetime import datetime, timedelta
from pymongo.errors import DuplicateKeyError

from api.routes.auth import db

members_bp = Blueprint('members', __name__)

# Helpers
def convert_member_to_response(member):
    member['id'] = str(member['_id'])
    del member['_id']
    return member


@members_bp.route('/', methods=['GET'])
def get_members():
    skip = int(request.args.get('skip', 0))
    limit = int(request.args.get('limit', 20))
    search = request.args.get('search')
    is_active = request.args.get('is_active')

    query = {}
    if is_active is not None:
        query['is_active'] = is_active.lower() == 'true'

    if search:
        query['$or'] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"full_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]

    members = list(db.members.find(query).skip(skip).limit(limit))
    return jsonify([convert_member_to_response(m) for m in members])


@members_bp.route('/<member_id>', methods=['GET'])
def get_member(member_id):
    if not ObjectId.is_valid(member_id):
        return jsonify({'detail': 'Invalid member ID'}), 400

    member = db.members.find_one({'_id': ObjectId(member_id)})
    if not member:
        return jsonify({'detail': 'Member not found'}), 404

    return jsonify(convert_member_to_response(member))


@members_bp.route('/username/<username>', methods=['GET'])
def get_member_by_username(username):
    member = db.members.find_one({'username': username})
    if not member:
        return jsonify({'detail': 'Member not found'}), 404

    return jsonify(convert_member_to_response(member))


@members_bp.route('/', methods=['POST'])
def create_member():
    data = request.get_json()

    if db.members.find_one({'username': data['username']}):
        return jsonify({'detail': 'Username already exists'}), 400

    if db.members.find_one({'email': data['email']}):
        return jsonify({'detail': 'Email already exists'}), 400

    member_data = {
        **data,
        'joined_at': datetime.utcnow(),
        'is_active': True,
        'communities': []
    }

    result = db.members.insert_one(member_data)
    created_member = db.members.find_one({'_id': result.inserted_id})
    return jsonify(convert_member_to_response(created_member)), 201


@members_bp.route('/<member_id>', methods=['PUT'])
def update_member(member_id):
    data = request.get_json()
    current_user = 'user123'  # Replace with real auth

    if not ObjectId.is_valid(member_id):
        return jsonify({'detail': 'Invalid member ID'}), 400

    member = db.members.find_one({'_id': ObjectId(member_id)})
    if not member:
        return jsonify({'detail': 'Member not found'}), 404

    if member['username'] != current_user:
        return jsonify({'detail': 'Not authorized'}), 403

    if data['username'] != member['username'] and db.members.find_one({'username': data['username']}):
        return jsonify({'detail': 'Username already exists'}), 400

    if data['email'] != member['email'] and db.members.find_one({'email': data['email']}):
        return jsonify({'detail': 'Email already exists'}), 400

    db.members.update_one({'_id': ObjectId(member_id)}, {'$set': data})
    updated = db.members.find_one({'_id': ObjectId(member_id)})
    return jsonify(convert_member_to_response(updated))


@members_bp.route('/<member_id>', methods=['DELETE'])
def delete_member(member_id):
    current_user = 'user123'

    if not ObjectId.is_valid(member_id):
        return jsonify({'detail': 'Invalid member ID'}), 400

    member = db.members.find_one({'_id': ObjectId(member_id)})
    if not member:
        return jsonify({'detail': 'Member not found'}), 404

    if member['username'] != current_user:
        return jsonify({'detail': 'Not authorized'}), 403

    db.members.update_one({'_id': ObjectId(member_id)}, {'$set': {'is_active': False}})
    db.communities.update_many({}, {'$pull': {'members': member_id}, '$inc': {'member_count': -1}})

    return '', 204


@members_bp.route('/<member_id>/communities', methods=['GET'])
def get_member_communities(member_id):
    if not ObjectId.is_valid(member_id):
        return jsonify({'detail': 'Invalid member ID'}), 400

    member = db.members.find_one({'_id': ObjectId(member_id)})
    if not member:
        return jsonify({'detail': 'Member not found'}), 404

    community_ids = [ObjectId(cid) for cid in member.get('communities', []) if ObjectId.is_valid(cid)]
    if not community_ids:
        return jsonify([])

    communities = db.communities.find({'_id': {'$in': community_ids}})
    return jsonify([
        {
            'id': str(c['_id']),
            'name': c['name'],
            'description': c['description'],
            'member_count': c.get('member_count', 0),
            'is_public': c.get('is_public', True),
            'avatar_url': c.get('avatar_url')
        } for c in communities
    ])


@members_bp.route('/<member_id>/activity', methods=['GET'])
def get_member_activity(member_id):
    days = int(request.args.get('days', 30))
    if not ObjectId.is_valid(member_id):
        return jsonify({'detail': 'Invalid member ID'}), 400

    member = db.members.find_one({'_id': ObjectId(member_id)})
    if not member:
        return jsonify({'detail': 'Member not found'}), 404

    username = member['username']
    from_date = datetime.utcnow() - timedelta(days=days)

    threads = db.threads.count_documents({
        'created_by': username,
        'created_at': {'$gte': from_date}
    })

    messages = db.messages.count_documents({
        'author': username,
        'created_at': {'$gte': from_date}
    })

    return jsonify({
        'member_id': member_id,
        'username': username,
        'period_days': days,
        'threads_created': threads,
        'messages_posted': messages,
        'communities_joined': len(member.get('communities', [])),
        'activity_score': threads * 5 + messages
    })
