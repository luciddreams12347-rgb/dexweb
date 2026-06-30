from collections import deque
from contextlib import contextmanager

import pymysql
from flask import current_app


@contextmanager
def db_cursor():
    if not current_app.config.get("DB_ENABLED"):
        yield None
        return
    connection = pymysql.connect(
        host=current_app.config["DB_HOST"],
        port=current_app.config["DB_PORT"],
        user=current_app.config["DB_USER"],
        password=current_app.config["DB_PASSWORD"],
        database=current_app.config["DB_NAME"],
        autocommit=True,
    )
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
        connection.close()


def log_action(username, action):
    try:
        with db_cursor() as cursor:
            if cursor is not None:
                cursor.execute("INSERT INTO logs (username, action) VALUES (%s, %s)", (username, action))
    except Exception:
        current_app.logger.exception("Could not write audit log")


def is_banned(username, feature):
    try:
        with db_cursor() as cursor:
            if cursor is None:
                return False
            cursor.execute("SELECT expires_at FROM bans WHERE username=%s AND feature=%s", (username, feature))
            row = cursor.fetchone()
            if not row:
                return False
            expires_at = row[0]
            if expires_at is None:
                return True
            from datetime import datetime

            if datetime.now() < expires_at:
                return True
            cursor.execute("DELETE FROM bans WHERE username=%s AND feature=%s", (username, feature))
            return False
    except Exception:
        current_app.logger.exception("Could not check ban")
        return False


def fetch_user(username):
    with db_cursor() as cursor:
        if cursor is None:
            return None
        cursor.execute("SELECT password, grade FROM users WHERE username=%s", (username,))
        return cursor.fetchone()


def create_user(username, password_hash, grade):
    with db_cursor() as cursor:
        if cursor is not None:
            cursor.execute(
                "INSERT INTO users (username, password, grade) VALUES (%s, %s, %s)",
                (username, password_hash, grade),
            )


def fetch_admin_data():
    with db_cursor() as cursor:
        if cursor is None:
            return [], [], []
        cursor.execute("SELECT username, action, created_at FROM logs ORDER BY created_at DESC LIMIT 20")
        logs = cursor.fetchall()
        cursor.execute("SELECT username, grade FROM users")
        users = cursor.fetchall()
        cursor.execute("SELECT username, feature, expires_at FROM bans")
        bans = cursor.fetchall()
        return logs, users, bans


def apply_admin_action(action, username="", feature="", days=0, hours=0, minutes=0):
    from datetime import datetime, timedelta

    with db_cursor() as cursor:
        if cursor is None:
            return
        if action == "remove_user" and username:
            cursor.execute("DELETE FROM users WHERE username=%s", (username,))
            log_action("ADMIN", f"Removed user {username}")
        elif action == "ban_user" and username and feature:
            expires_at = datetime.now() + timedelta(days=days, hours=hours, minutes=minutes)
            cursor.execute(
                """
                INSERT INTO bans (username, feature, expires_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE expires_at=VALUES(expires_at)
                """,
                (username, feature, expires_at),
            )
            log_action("ADMIN", f"Banned {username} from {feature} until {expires_at}")
        elif action == "unban_user" and username and feature:
            cursor.execute("DELETE FROM bans WHERE username=%s AND feature=%s", (username, feature))
            log_action("ADMIN", f"Unbanned {username} from {feature}")


def tail_log(file_path, lines=20):
    if not file_path:
        return "(no site log configured)"
    try:
        recent = deque(maxlen=lines)
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                recent.append(line)
        return "".join(recent)
    except OSError as error:
        return f"Could not read log: {error}"
