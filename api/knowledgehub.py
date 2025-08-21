from flask import Blueprint, request, jsonify
from bson import ObjectId
from datetime import datetime, timedelta

from pymongo import DESCENDING

from api.routes.auth import db, get_current_user

knowledge_hub_bp = Blueprint("knowledgehub", __name__)



# 2️⃣ Get Articles
@knowledge_hub_bp.route("/knowledge/articles/list", methods=["GET"])
def get_articles():
    articles = list(db.articles.find({}, {"_id": 0}))
    return jsonify({"status": "success", "articles": articles})


# 3️⃣ Add Article
@knowledge_hub_bp.route("/knowledge/articles/create", methods=["POST"])
def add_article():
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"status": "error", "message": "Token is missing"}), 401

        user = get_current_user(auth_header)
        data = request.json

        # Validate required fields
        if not data.get("title") or not data.get("content") or not data.get("status"):
            return jsonify({"status": "error", "message": "Missing required fields"}), 400

        article = {
            "title": data["title"],
            "content": data["content"],
            "thumbnail": data.get("thumbnail", ""),
            "excerpt": data.get("excerpt", ""),
            "category": data.get("category", ""),
            "tags": data.get("tags", []),
            "status": data.get("status", "draft"),

            # default counters
            "views": 0,
            "likes": 0,
            "comments": 0,
            "engagement": 0,

            # premium flag
            "is_premium": data.get("is_premium", False),

            # author + timestamps
            "publish_date": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "author_id": user["_id"],
            "author_name": user.get("full_name", "")
        }

        # Insert into DB
        db.articles.insert_one(article)

        return jsonify({"status": "success", "message": "Article added successfully"}), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_hub_bp.route("/knowledge/articles/myarticles", methods=["GET"])
def get_my_articles():
    auth_header = request.headers.get("Authorization")
    user = get_current_user(auth_header)

    articles = list(db.articles.find(
        {"author_id": user["_id"]},
        {"title": 1, "status": 1, "publish_date": 1, "author_name": 1, "created_at": 1}
    ).sort("publish_date", DESCENDING))

    # Convert ObjectId to string
    for a in articles:
        a["id"] = str(a["_id"])
        a.pop("_id", None)
        a["publish_date"] = a["publish_date"].isoformat() if a.get("publish_date") else None

    return jsonify({"status": "success", "articles": articles}), 200


# Get article for editing
@knowledge_hub_bp.route("/knowledge/articles/edit/<article_id>", methods=["GET"])
def get_article(article_id):
    auth_header = request.headers.get("Authorization")
    user = get_current_user(auth_header)

    article = db.articles.find_one({"_id": ObjectId(article_id), "author_id": user["_id"]})
    if not article:
        return jsonify({"status": "error", "message": "Article not found"}), 404

    article["id"] = str(article["_id"])
    article["author_id"] = str(article["author_id"])
    article.pop("_id", None)
    article["publish_date"] = article["publish_date"].isoformat() if article.get("publish_date") else None

    return jsonify({"status": "success", "article": article}), 200


# Update existing article
@knowledge_hub_bp.route("/knowledge/articles/update/<article_id>", methods=["PUT"])
def update_article(article_id):
    auth_header = request.headers.get("Authorization")
    user = get_current_user(auth_header)

    article = db.articles.find_one({"_id": ObjectId(article_id), "author_id": user["_id"]})
    if not article:
        return jsonify({"status": "error", "message": "Article not found"}), 404

    data = request.json
    data["last_modified"] = datetime.utcnow()

    db.articles.update_one({"_id": ObjectId(article_id)}, {"$set": data})
    return jsonify({"status": "success", "message": "Article updated"}), 200


# 4️⃣ Get Leaderboard
@knowledge_hub_bp.route("/knowledge/leaderboard", methods=["GET"])
def get_leaderboard():
    leaderboard = list(db.leaderboard.find({}, {"_id": 0}))
    return jsonify({"status": "success", "leaderboard": leaderboard})


# 5️⃣ Get Categories
@knowledge_hub_bp.route("/knowledge/categories", methods=["GET"])
def get_categories():
    categories = list(db.categories.find({}, {"_id": 0}))
    return jsonify({"status": "success", "categories": categories})


@knowledge_hub_bp.route("/knowledge/articles/list/<filter_type>", methods=["GET"])
def list_articles(filter_type):
    query = {"status": "published"}
    sort_field = None
    sort_order = -1
    if filter_type == "trending":
        # trending = based on engagement (views+likes+comments)
        sort_field = "engagement"
    elif filter_type == "recent":
        sort_field = "publish_date"
    elif filter_type == "most-read":
        sort_field = "views"
    elif filter_type == "premium":
        query["is_premium"] = True
        sort_field = "publish_date"
    else:
        return jsonify({"status": "error", "message": "Invalid filter"}), 400

    articles = list(
        db.articles.find(query).sort(sort_field, sort_order).limit(20)
    )

    return jsonify({
        "status": "success",
        "articles": [serialize_article(a) for a in articles]
    })


def serialize_article(article):
    return {
        "id": str(article["_id"]),
        "title": article.get("title"),
        "author": article.get("author_name"),
        "avatar": article.get("author_name", "")[:2].upper(),  # initials
        "expertise": "Expert",  # you can extend later
        "publishDate": article.get("publish_date"),
        "readTime": "5 min read",  # placeholder, or calculate
        "category": article.get("category", "General"),
        "tags": article.get("tags", []),
        "views": article.get("views", 0),
        "likes": article.get("likes", 0),
        "comments": article.get("comments", 0),
        "engagement": article.get("engagement", 0),
        "thumbnail": article.get("thumbnail", ""),
        "excerpt": article.get("excerpt", ""),
        "isPremium": article.get("is_premium", False),
        "isVerified": True  # you can decide how to flag verified
    }


@knowledge_hub_bp.route("/knowledge/stats", methods=["GET"])
def get_stats():
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"status": "error", "message": "Token is missing"}), 401
        now = datetime.utcnow()
        one_day_ago = now - timedelta(days=1)
        one_week_ago = now - timedelta(weeks=1)
        one_month_ago = now - timedelta(days=30)

        # Published Articles
        total_published = db.articles.count_documents({"status": "published"})
        published_last_week = db.articles.count_documents({
            "status": "published",
            "publish_date": {"$gte": one_week_ago}
        })

        # Readers (views)
        readers_cursor = db.articles.aggregate([{"$group": {"_id": None, "views": {"$sum": "$views"}}}])
        total_views = next(readers_cursor, {}).get("views", 0)

        readers_today_cursor = db.articles.aggregate([
            {"$match": {"updated_at": {"$gte": one_day_ago}}},
            {"$group": {"_id": None, "views": {"$sum": "$views"}}}
        ])
        today_views = next(readers_today_cursor, {}).get("views", 0)

        # Expert Authors
        total_authors = len(db.articles.distinct("author_id", {"status": "published"}))
        new_authors_month = len(db.articles.distinct("author_id", {
            "status": "published",
            "publish_date": {"$gte": one_month_ago}
        }))

        # Avg Engagement
        eng_cursor = db.articles.aggregate([{"$group": {"_id": None, "avg": {"$avg": "$engagement"}}}])
        avg_engagement = round(next(eng_cursor, {}).get("avg", 0), 2)

        eng_prev_cursor = db.articles.aggregate([
            {"$match": {"publish_date": {"$gte": one_week_ago}}},
            {"$group": {"_id": None, "avg": {"$avg": "$engagement"}}}
        ])
        last_week_eng = round(next(eng_prev_cursor, {}).get("avg", 0), 2)

        return jsonify({
            "status": "success",
            "data": {
                "published_articles": {
                    "value": total_published,
                    "change": f"+{published_last_week} this week"
                },
                "total_readers": {
                    "value": total_views,
                    "change": f"+{today_views} today"
                },
                "expert_authors": {
                    "value": total_authors,
                    "change": f"+{new_authors_month} this month"
                },
                "avg_engagement": {
                    "value": avg_engagement,
                    "change": f"{avg_engagement - last_week_eng:+} points"
                }
            }
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_hub_bp.route("/knowledge/articles/<article_id>/interact", methods=["POST"])
def interact_article(article_id):
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"status": "error", "message": "Token is missing"}), 401

        user = get_current_user(auth_header)
        user_id = str(user["_id"])
        data = request.json
        action = data.get("action")  # "view" or "like"

        article = db.articles.find_one({"_id": ObjectId(article_id)})
        if not article:
            return jsonify({"status": "error", "message": "Article not found"}), 404

        update_query = {}
        if action == "view":
            if user_id not in article.get("viewed_by", []):
                update_query = {
                    "$inc": {"views": 1},
                    "$addToSet": {"viewed_by": user_id}
                }
        elif action == "like":
            if user_id not in article.get("liked_by", []):
                update_query = {
                    "$inc": {"likes": 1},
                    "$addToSet": {"liked_by": user_id}
                }

        if update_query:
            db.articles.update_one({"_id": ObjectId(article_id)}, update_query)

        # return updated counts
        updated_article = db.articles.find_one({"_id": ObjectId(article_id)}, {"views": 1, "likes": 1})
        return jsonify({
            "status": "success",
            "data": {
                "views": updated_article.get("views", 0),
                "likes": updated_article.get("likes", 0)
            }
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500