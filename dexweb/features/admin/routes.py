from flask import current_app, redirect, render_template, request, session, url_for

from ...database import apply_admin_action, fetch_admin_data, tail_log
from ...routes import main


def _int_form(name):
    try:
        return max(0, int(request.form.get(name) or 0))
    except ValueError:
        return 0


@main.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    message = ""
    if request.method == "POST":
        if request.form.get("password") == current_app.config["ADMIN_PASSWORD"]:
            session["is_admin"] = True
            session.setdefault("user", "ADMIN")
            return redirect(url_for("main.admin"))
        message = "Invalid admin password!"
    return render_template("admin_login.html", message=message)


@main.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("is_admin"):
        return redirect(url_for("main.admin_login"))
    if request.method == "POST":
        apply_admin_action(
            request.form.get("action", ""),
            username=(request.form.get("username") or "").strip(),
            feature=(request.form.get("feature") or "").strip(),
            days=_int_form("days"),
            hours=_int_form("hours"),
            minutes=_int_form("minutes"),
        )
    logs, users, bans = fetch_admin_data()
    ban_map = {}
    for username, feature, expires_at in bans:
        ban_map.setdefault(username, []).append((feature, expires_at))
    return render_template(
        "admin.html",
        users=users,
        ban_map=ban_map,
        logs=logs,
        site_logs=tail_log(current_app.config.get("SITE_LOG_PATH")),
        db_enabled=current_app.config.get("DB_ENABLED"),
    )
