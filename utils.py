import json
import os

import redis
from flask import request, jsonify
from datetime import datetime
from werkzeug.utils import secure_filename
from pdf2image import convert_from_path
from PyPDF2 import PdfReader

# Connect to Redis (adjust host/port/db if needed)
redis_client = redis.Redis(host='localhost', port=6379, db=0)
BASE_URL = "http://localhost:5001"

UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
THUMBNAIL_FOLDER = os.path.join(UPLOAD_FOLDER, "thumbnails")
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)





def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def publish_member_event(channel: str, data: dict):
    message = json.dumps(data)
    redis_client.publish(channel, message)


def upload_file(file):
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = secure_filename(f"{datetime.utcnow().timestamp()}_{file.filename}")
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        thumbnail_url = None

        # Generate thumbnail
        if ext in ['jpg', 'jpeg']:
            thumbnail_url = f"{BASE_URL}/uploads/thumbnails/{filename}"
        elif ext == 'pdf':
            images = convert_from_path(filepath, first_page=1, last_page=1, dpi=100)
            thumb_name = f"{filename}.jpg"
            thumb_path = os.path.join(THUMBNAIL_FOLDER, thumb_name)
            images[0].save(thumb_path, 'JPEG')
            thumbnail_url = f"{BASE_URL}/uploads/thumbnails/{thumb_name}"

        file_url = f"{BASE_URL}/uploads/{filename}"
        return file_url, thumbnail_url, ext
