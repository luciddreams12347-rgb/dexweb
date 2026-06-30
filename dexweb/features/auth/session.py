from flask import session


def login_required():
    return "user" in session


def parse_grade(value):
    return int(value) if value in {"9", "10", "11"} else None
