from flask import session


def user_logged_in():
    return "user" in session


def user_is_admin():
    return bool(session.get("is_admin"))

