from flask import redirect, render_template, request, session, url_for

from ...database import is_banned, log_action
from ...routes import main
from ..auth.session import login_required
from .service import clear_conversation, get_conversation, get_dex_service, record_exchange


@main.route("/dex", methods=["GET", "POST"])
def dex():
    if not login_required():
        return redirect(url_for("main.login"))

    username = session["user"]
    if is_banned(username, "dex"):
        return render_template("message.html", message="You are banned from DEX."), 403

    error = ""
    if request.method == "POST":
        action = request.form.get("action", "send")
        if action == "clear":
            clear_conversation(session)
            log_action(username, "Cleared DEX conversation")
            return redirect(url_for("main.dex"))

        prompt = request.form.get("prompt", "").strip()
        if not prompt:
            error = "Enter a message to send to DEX."
        else:
            history = get_conversation(session)
            response = get_dex_service().process(
                prompt=prompt,
                messages=list(history),
                context={"feature": "dex-chat"},
                user=username,
            )
            if response.get("ok"):
                record_exchange(session, prompt, response["content"])
                log_action(username, "Sent message to DEX")
                return redirect(url_for("main.dex"))
            error = "DEX could not process your message. Try again."

    return render_template(
        "dex.html",
        user=username,
        messages=session.get("dex_messages", []),
        error=error,
    )
