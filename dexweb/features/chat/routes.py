from flask import redirect, render_template, request, session, url_for

from ...database import is_banned, log_action
from ...routes import main
from ..auth.session import login_required
from .service import add_message, format_messages, get_recent_messages, room_display_name, room_exists, user_can_enter_room


@main.route("/chat")
def chat_index():
    if not login_required():
        return redirect(url_for("main.login"))
    return render_template("chat_index.html")


@main.route("/chat/<room>", methods=["GET", "POST"])
def chat_room(room):
    room = room.lower()
    if not room_exists(room):
        return render_template("message.html", message="Invalid room"), 404
    if not login_required():
        return redirect(url_for("main.login"))

    username = session["user"]
    grade = session.get("grade")
    is_admin = session.get("is_admin", False)
    allowed = user_can_enter_room(room, grade, is_admin)
    if is_banned(username, f"chat:{room}"):
        return render_template("message.html", message="You are banned from this chat room."), 403

    if request.method == "POST":
        if not allowed:
            return render_template("message.html", message="Not allowed"), 403
        text = request.form.get("text", "").strip()
        if text:
            add_message(room, username, grade, is_admin, text)
            log_action(username, f"Sent message in {room}")
        return redirect(url_for("main.chat_room", room=room))

    messages = format_messages(get_recent_messages(room, limit=50))
    if request.args.get("_ajax") == "1":
        return render_template("partials/chat_messages.html", messages=messages)
    return render_template(
        "chat_room.html",
        room=room,
        room_name=room_display_name(room),
        messages=messages,
        allowed=allowed,
    )
