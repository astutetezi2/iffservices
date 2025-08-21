from datetime import datetime

def validate_community_input(data):
    required_fields = ["name", "description", "created_by", "is_public"]
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    validated_data = {
        "name": data["name"],
        "description": data["description"],
        "created_by": data["created_by"],
        "created_at": datetime.utcnow(),
        "member_count": data.get("member_count", 0),
        "is_public": bool(data["is_public"]),
        "tags": data.get("tags", []),
        "avatar": data.get("avatar", ""),
        "color": data.get("color", "")
    }

    return validated_data