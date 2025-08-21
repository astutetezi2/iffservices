import json

from fastapi import Depends, HTTPException, status
from flask import Blueprint, request, jsonify, Request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from jose import JWTError, jwt
from passlib.context import CryptContext
from pymongo import MongoClient
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer
import configparser
import redis
import os
from bson import ObjectId

from starlette.responses import JSONResponse

config = configparser.ConfigParser()
config.read('config.ini')
MONGO_URI = os.getenv("MONGO_URI", config['database']['mongo_uri'])
DB_NAME = os.getenv("MONGO_DB_NAME", config['database']['db_name'])

# JWT
JWT_SECRET_KEY = os.getenv("JWT_SECRET", config['jwt']['secret'])
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", config['jwt']['algorithm'])
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", 60 * 24))  # default 1 day

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", config['redis']['host'])
REDIS_PORT = int(os.getenv("REDIS_PORT", config['redis']['port']))
REDIS_DB = int(os.getenv("REDIS_DB", config['redis']['db']))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)  # optional

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True
)

# MongoDB connection
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]

# Example collection
members = db["members"]

# Password hasher
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

auth_bp = (Blueprint('auth', __name__))


# Password helpers
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


# JWT helpers
def create_access_token(data: dict, expires_delta: timedelta = None):
    print(f"Algorithm: {JWT_ALGORITHM} | Type: {type(JWT_ALGORITHM)}")
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


# Auth logic
def authenticate_user(username_or_email: str, password: str):
    user = members.find_one({
        "$or": [
            {"username": username_or_email},
            {"email": username_or_email}
        ]
    })

    if not user or not verify_password(password, user.get("hashed_password", "")):
        return None
    return user


# Dependency
def get_current_user(auth_header):
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = auth_header.split(" ")[1]
    if redis_client.get(f"blacklist:{token}"):
        raise HTTPException(status_code=401, detail="Token expired or blacklisted")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    user = members.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()  # handles application/json
    username = data.get('username')
    password = data.get('password')
    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = str(user["_id"])
    access_token = create_access_token(
        data={"sub": str(user["_id"])},
        expires_delta=timedelta(minutes=60 * 24)
    )
    redis_client.setex(f"token:{access_token}", 60 * 60 * 24, user_id)
    for community_id in user.get("communities", []):
        redis_client.sadd(f"community:{community_id}:online_users", user_id)
        redis_client.publish(f"community:{community_id}", json.dumps({
            "event": "join",
            "community_id": community_id,
            "user_id": user_id
        }))

    return {"access_token": access_token, "token_type": "bearer", "logged_user_id": user_id,
            "designation": user.get("onboarding")["designation"], "logged_user_name": user.get("full_name")}


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Token is missing"}), 401
    token = auth_header.split(" ")[1]
    user = get_current_user(auth_header)
    user_id = str(user["_id"])
    redis_client.setex(f"blacklist:{token}", timedelta(minutes=JWT_EXPIRE_MINUTES), "true")
    for community_id in user.get("communities", []):
        redis_client.srem(f"community:{community_id}:online_users", user_id)
    redis_client.delete(f"token:{token}")
    return jsonify({"code": "200", "message": "Successfully logged out"}), 200


# Current User Route
@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def read_current_user():
    identity = get_jwt_identity()
    return jsonify({
        "username": identity.get("username"),
        "email": identity.get("email"),
        "full_name": identity.get("full_name"),
        "is_active": identity.get("is_active"),
        "joined_at": identity.get("joined_at"),
    }), 200
