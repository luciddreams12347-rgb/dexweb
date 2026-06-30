import pymysql
from flask import current_app, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ...database import create_user, fetch_user, log_action
from ...routes import main
from .session import parse_grade


@main.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        grade = parse_grade(request.form.get("grade", "").strip())
        if not username:
            message = "Username is required."
        elif current_app.config.get("DB_ENABLED"):
            try:
                row = fetch_user(username)
                if row:
                    password_hash, existing_grade = row[0], row[1]
                    if check_password_hash(password_hash, password):
                        session["user"] = username
                        session["grade"] = existing_grade
                        log_action(username, "Logged in")
                        return redirect(url_for("main.home"))
                    message = "Invalid password!"
                elif grade is None:
                    message = "New username - please select a grade to register."
                else:
                    create_user(username, generate_password_hash(password), grade)
                    session["user"] = username
                    session["grade"] = grade
                    log_action(username, "Created account")
                    return redirect(url_for("main.home"))
            except pymysql.err.IntegrityError:
                message = "Username already exists - choose another."
            except Exception:
                current_app.logger.exception("Login failed")
                message = "Login is temporarily unavailable."
        else:
            session["user"] = username
            session["grade"] = grade
            session["is_admin"] = False
            return redirect(url_for("main.home"))
    return render_template("login.html", message=message)


@main.route("/logout")
def logout():
    if "user" in session:
        log_action(session["user"], "Logged out")
    session.clear()
    return redirect(url_for("main.index"))
