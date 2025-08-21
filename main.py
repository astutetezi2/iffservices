import asyncio
import logging
import json
import configparser
import os
import threading
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sock import Sock
from hypercorn.config import Config
from hypercorn.asyncio import serve
from redis import Redis
from pymongo import MongoClient

from models.database import database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config.ini
config = configparser.ConfigParser()
config.read('config.ini')

# Create Flask app
app = Flask(__name__)
CORS(app)
sock = Sock(app)

# Config
app.config['JWT_SECRET_KEY'] = config['jwt']['secret']
app.config['JWT_ALGORITHM'] = config['jwt'].get('algorithm', 'HS256')

# Setup JWT
jwt = JWTManager(app)

# Setup Redis
redis_client = Redis(
    host=config['redis']['host'],
    port=int(config['redis']['port']),
    db=int(config['redis']['db']),
    decode_responses=True
)

# ------------------------------
# Import AFTER app is created
# ------------------------------
from services.redis_broker import redis_broker
from services.websocket_manager import manager, handle_websocket_message
from api.communities import communities_bp
from api.threads import threads_bp
from api.messages import messages_bp
from api.members import members_bp
from api.routes.auth import auth_bp, pwd_context, get_current_user, db
from api.profile import profile_bp
from api.routes.activity import  activity_bp
from api.knowledgehub import knowledge_hub_bp

# Register Blueprints
app.register_blueprint(communities_bp, url_prefix='/api/communities')
app.register_blueprint(threads_bp, url_prefix='/api/threads')
app.register_blueprint(messages_bp, url_prefix='/api/messages')
app.register_blueprint(members_bp, url_prefix='/api/members')
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(profile_bp, url_prefix='/api/profile')
app.register_blueprint(activity_bp, url_prefix='/api/activity')
app.register_blueprint(knowledge_hub_bp, url_prefix='/api/hub')


# -------------------------------
# Redis Listener (async in thread)
# -------------------------------
async def redis_message_handler(channel: str, message_data: dict):
    try:
        message_type = message_data.get('type')

        if channel.startswith('community:'):
            community_id = channel.split(':', 1)[1]
            await manager.broadcast_to_community(community_id, message_data)
        elif channel.startswith('thread:'):
            thread_id = channel.split(':', 1)[1]
            await manager.broadcast_to_thread(thread_id, message_data)
        elif channel == 'global:notifications':
            await manager.broadcast_to_all(message_data)

        logger.info(f"Broadcasted {message_type} message from channel {channel}")

    except Exception as e:
        logger.error(f"Error handling Redis message: {e}")


async def listen_to_redis():
    try:
        await redis_broker.connect()
        await redis_broker.subscribe('community:*', redis_message_handler)
        await redis_broker.subscribe('thread:*', redis_message_handler)
        await redis_broker.subscribe('global:*', redis_message_handler)
        await redis_broker.listen()
    except Exception as e:
        logger.error(f"Redis listener failed: {e}")


def start_redis_listener_in_background():
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(listen_to_redis())

    threading.Thread(target=run, daemon=True).start()


# --------------------------
# App initialization
# --------------------------
def initialize_app():
    logger.info("Initializing Communities Backend Server...")

    with app.app_context():
        # Connect to MongoDB (sync version)
        database.connect_to_mongo_sync()

        # Start Redis listener in background thread
        start_redis_listener_in_background()

    logger.info("Communities Backend Server initialized")


# --------------------------
# Routes
# --------------------------

@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "message": "Communities Backend API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "communities": "/api/communities",
            "threads": "/api/threads",
            "messages": "/api/messages",
            "members": "/api/members",
            "auth": "/api/auth",
            "websocket": "/ws/<user_id>",
            "docs": "/docs"
        }
    })


@app.route("/health", methods=["GET"])
def health_check():
    try:
        database.database.admin.command('ping')
        mongo_status = "healthy"
    except Exception as e:
        mongo_status = f"unhealthy: {str(e)}"

    try:
        if redis_broker.redis_client:
            redis_broker.redis_client.ping()
            redis_status = "healthy"
        else:
            redis_status = "not connected"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"

    ws_connections = manager.get_connection_count()

    return jsonify({
        "status": "running",
        "mongodb": mongo_status,
        "redis": redis_status,
        "websocket_connections": ws_connections,
        "timestamp": datetime.utcnow().isoformat()
    })


@sock.route("/ws/<path:token>")
def websocket_route_old(ws, token):
    print("TOKEN:", token)
    try:
        user = get_current_user(token)
        user_id= user.get('_id')
        manager.sync_connect(ws, user_id)
        logger.info(f"WebSocket connected for user: {user_id}")

        while True:
            data = ws.receive()
            if data is None:
                break
            try:
                message = json.loads(data)
                asyncio.run(handle_websocket_message(ws, message))
            except json.JSONDecodeError:
                ws.send(json.dumps({"type": "error", "message": "Invalid JSON format"}))
            except Exception as e:
                logger.error(f"WebSocket message error: {e}")
                ws.send(json.dumps({"type": "error", "message": "Failed to process message"}))

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.sync_disconnect(ws)
        logger.info(f"WebSocket disconnected for user: {user_id}")


@sock.route('/ws-echo/<token>')
def websocket_route(ws, token):
    print(f"New connection with token: {token}")
    while True:
        data = ws.receive()
        if data is None:
            break
        print(f"Received: {data}")
        ws.send(f"Echo: {data}")

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    return jsonify({"error": True, "message": "Internal server error", "status_code": 500}), 500


# Route to serve files
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
THUMBNAIL_FOLDER = os.path.join(UPLOAD_FOLDER, "thumbnails")

@app.route("/uploads/<path:filename>")
def serve_uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# Route to serve thumbnails
@app.route("/uploads/thumbnails/<path:filename>")
def serve_thumbnail(filename):
    return send_from_directory(THUMBNAIL_FOLDER, filename)


def db_script_test():
    FOLLOWS_COLLECTION = "follows"
    MEMBERS_COLLECTION = "members"
    follows_col = db[FOLLOWS_COLLECTION]
    members_col = db[MEMBERS_COLLECTION]

    # ==== MIGRATION ====
    updated_count = 0

    for follow_doc in follows_col.find({}):
        try:
            follower_obj = follow_doc.get("follower", {})
            followee_obj = follow_doc.get("followee", {})

            follower_id = follower_obj.get("_id") if isinstance(follower_obj, dict) else None
            followee_id = followee_obj.get("_id") if isinstance(followee_obj, dict) else None

            if not follower_id or not followee_id:
                print(f"Skipping follow doc {follow_doc.get('_id')} - missing IDs")
                continue

            # Get followee details from members collection in case of missing fields
            followee_profile = members_col.find_one(
                {"_id": followee_id},
                {"full_name": 1, "username": 1, "avatar_url": 1}
            ) or {}

            update_data = {
                "follower_id": follower_id,
                "followee_id": followee_id,
                "followee_name": followee_profile.get("full_name", followee_obj.get("full_name")),
                "followee_username": followee_profile.get("username", followee_obj.get("username")),
                "followee_avatar": followee_profile.get("avatar_url", followee_obj.get("avatar_url"))
            }

            follows_col.update_one(
                {"_id": follow_doc["_id"]},
                {"$set": update_data}
            )

            updated_count += 1

        except Exception as e:
            print(f"Error processing doc {follow_doc.get('_id')}: {e}")
# --------------------------
# Entry Point
# --------------------------
if __name__ == "__main__":
    initialize_app()
    hashed = pwd_context.hash("Sachin@123")
    print("Hash:", hashed)
    assert pwd_context.verify("Sachin@123", hashed)
    # app.run(host="0.0.0.0", port=5001, debug=True)
    # db_script_test()

    config = Config()
    config.bind = ["0.0.0.0:5001"]
    config.debug = True
    config.accesslog = "-"
    config.worker_class = "asyncio"
    asyncio.run(serve(app, config))
