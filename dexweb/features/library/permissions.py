from flask import session


def user_logged_in():
    return "user" in session


def user_is_admin():
    return bool(session.get("is_admin"))


def user_can_view_worm_job(job, actor, is_admin=False):
    if not job or not actor:
        return False
    if is_admin:
        return True
    uploader = getattr(job, "uploader", None)
    return bool(uploader and uploader == actor)

