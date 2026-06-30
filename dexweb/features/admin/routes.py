from flask import Response, current_app, redirect, render_template, request, session, url_for

from ...database import apply_admin_action, fetch_admin_data, tail_log
from ...features.dex.service import get_dex_service
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
    admin_message = ""
    if request.method == "POST":
        action = request.form.get("action", "")
        dex_service = get_dex_service()
        if action == "dex_save_prompt":
            dex_service.save_system_prompt(request.form.get("dex_system_prompt", ""))
            admin_message = "DEX system prompt saved."
        elif action == "dex_import_prompt":
            prompt_file = request.files.get("dex_prompt_file")
            if prompt_file and prompt_file.filename:
                dex_service.import_system_prompt(prompt_file)
                admin_message = "DEX system prompt imported."
            else:
                admin_message = "Choose a DEX prompt file to import."
        elif action == "dex_reset":
            dex_service.reset()
            admin_message = "DEX reset complete."
        else:
            apply_admin_action(
                action,
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
        dex_system_prompt=get_dex_service().get_system_prompt(),
        dex_provider=current_app.config.get("DEX_PROVIDER"),
        dex_model=current_app.config.get("DEX_MODEL") or "none",
        admin_message=admin_message,
    )


@main.route("/admin/dex/system-prompt.txt")
def export_dex_system_prompt():
    if not session.get("is_admin"):
        return redirect(url_for("main.admin_login"))
    prompt = get_dex_service().export_system_prompt()
    return Response(
        prompt,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=dex-system-prompt.txt"},
    )
