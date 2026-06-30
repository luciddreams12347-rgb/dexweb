from datetime import datetime, timezone

from flask import current_app, has_app_context

from ...site_config import SITE_CONFIG


_messages = {}


def configured_rooms():
    return [room["key"] for room in _site()["rooms"]]


def _site():
    if has_app_context():
        return current_app.config["SITE"]
    return SITE_CONFIG


def ensure_rooms():
    for room in configured_rooms():
        _messages.setdefault(room, [])


def clear_messages():
    _messages.clear()


def add_message(room, username, grade, is_admin, text):
    ensure_rooms()
    if room not in _messages:
        return False
    _messages[room].append(
        {
            "username": username,
            "grade": grade,
            "is_admin": bool(is_admin),
            "text": text,
            "ts": datetime.now(timezone.utc),
        }
    )
    max_messages = current_app.config.get("MAX_MESSAGES_PER_ROOM", 200) if has_app_context() else 200
    if len(_messages[room]) > max_messages:
        _messages[room] = _messages[room][-max_messages:]
    return True


def get_recent_messages(room, limit=50):
    ensure_rooms()
    return list(_messages.get(room, [])[-limit:])


def room_display_name(room):
    if room == "general":
        return "General"
    if room.startswith("grade"):
        return "Grade " + room.replace("grade", "")
    return room.title()


def room_exists(room):
    return room in [item["key"] for item in _site()["rooms"]]


def user_can_enter_room(room, grade=None, is_admin=False):
    if not room_exists(room):
        return False
    if room == "general" or is_admin:
        return True
    if room.startswith("grade"):
        try:
            return int(room.replace("grade", "")) == grade
        except ValueError:
            return False
    return False


def format_messages(messages):
    site = _site()
    display = []
    for message in messages:
        if message["is_admin"]:
            tag = site["admin_tag"]
        else:
            tag = site["grade_tags"].get(message["grade"], {"label": "U", "color": "#999999"})
        display.append(
            {
                "username": message["username"],
                "tag_color": tag["color"],
                "tag_label": tag["label"],
                "text": message["text"],
                "ts": message["ts"].strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        )
    return display
