from pathlib import Path

from flask import current_app, redirect, render_template, request, session, url_for

from ...database import is_banned, log_action
from ...routes import main
from ..auth.session import login_required
from .permissions import user_is_admin
from .review import normalize_admin_action
from .service import get_library_service
from .uploads import save_upload


@main.route("/library")
def library_home():
    service = get_library_service()
    grade = request.args.get("grade")
    subject = request.args.get("subject", "").strip()
    grade_filter = int(grade) if grade and grade.isdigit() else None
    chapters = service.list_public_chapters()
    if grade_filter is not None:
        chapters = [row for row in chapters if row.get("grade") == grade_filter]
    if subject:
        chapters = [row for row in chapters if row.get("subject", "").lower() == subject.lower()]
    viewer_grade = session.get("grade")
    return render_template("library_home.html", chapters=chapters, viewer_grade=viewer_grade)


@main.route("/library/upload", methods=["GET", "POST"])
def library_upload():
    if not login_required():
        return redirect(url_for("main.login"))
    username = session["user"]
    if is_banned(username, "library"):
        return render_template("message.html", message="You are banned from Library uploads."), 403
    service = get_library_service()
    message = ""
    if request.method == "POST":
        file_storage = request.files.get("file")
        if not file_storage or not file_storage.filename:
            message = "Select a file to upload."
        else:
            grade_raw = (request.form.get("grade") or "").strip()
            grade = int(grade_raw) if grade_raw.isdigit() else None
            upload_meta = None
            try:
                upload_meta = save_upload(file_storage)
                upload = service.create_upload(
                    uploader=username,
                    filename=upload_meta["stored_filename"],
                    stored_path=upload_meta["stored_path"],
                    grade=grade,
                    subject=(request.form.get("subject") or "").strip() or "General",
                    title=(request.form.get("title") or "").strip(),
                    description=(request.form.get("description") or "").strip(),
                    original_filename=upload_meta["original_filename"],
                    mime_type=upload_meta["mime_type"],
                    file_size=upload_meta["file_size"],
                    sha256=upload_meta["sha256"],
                )
                review = service.run_worm(upload.id)
                log_action(username, f"Uploaded library source file={upload_meta['original_filename']} review_id={review.id}")
                return redirect(url_for("main.library_home"))
            except ValueError as error:
                if upload_meta:
                    try:
                        Path(upload_meta["stored_path"]).unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception("Could not remove failed upload")
                message = str(error)
            except Exception:
                if upload_meta:
                    try:
                        Path(upload_meta["stored_path"]).unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception("Could not remove failed upload")
                current_app.logger.exception("Library upload failed")
                message = "Upload could not be completed right now."
    return render_template("upload.html", message=message)


@main.route("/library/review", methods=["GET", "POST"])
def library_review_queue():
    if not user_is_admin():
        return redirect(url_for("main.admin_login"))
    service = get_library_service()
    message = ""
    if request.method == "POST":
        review_raw = request.form.get("review_id", "0") or "0"
        review_id = int(review_raw) if review_raw.isdigit() else 0
        action = normalize_admin_action(request.form.get("action", ""))
        if review_id and action:
            result = service.apply_review_action(
                review_id=review_id,
                action=action,
                actor=session.get("user", "ADMIN"),
                edits={
                    "chapter_id": request.form.get("chapter_id", ""),
                    "chapter_title": request.form.get("chapter_title", ""),
                    "section_title": request.form.get("section_title", ""),
                    "subject": request.form.get("subject", ""),
                    "grade": request.form.get("grade", ""),
                    "topics": request.form.get("topics", ""),
                    "content": request.form.get("content", ""),
                },
            )
            if result:
                message = result["message"]
        else:
            message = "Choose a valid review action."
    return render_template("review_queue.html", items=service.list_reviews(), message=message)


@main.route("/library/chapter/<int:chapter_id>")
def library_chapter(chapter_id):
    service = get_library_service()
    view = service.chapter_view(chapter_id)
    if not view:
        return render_template("message.html", message="Chapter not found or unpublished."), 404
    notice = ""
    viewer_grade = session.get("grade")
    chapter_grade = view["chapter"].get("grade")
    if viewer_grade and chapter_grade and chapter_grade > viewer_grade:
        notice = "This material is above your selected grade level."
    return render_template("chapter.html", view=view, notice=notice)


@main.route("/library/search")
def library_search():
    service = get_library_service()
    grade_raw = request.args.get("grade", "")
    grade = int(grade_raw) if grade_raw.isdigit() else None
    subject = request.args.get("subject", "").strip() or None
    topic = request.args.get("topic", "").strip() or None
    keyword = request.args.get("q", "").strip() or None
    results = service.search_public(grade=grade, subject=subject, topic=topic, keyword=keyword)
    return render_template("search.html", results=results)


@main.route("/admin/library", methods=["GET", "POST"])
def admin_library():
    if not user_is_admin():
        return redirect(url_for("main.admin_login"))
    service = get_library_service()
    message = ""
    chapter_arg = request.args.get("chapter_id", "0") or "0"
    chapter_id = int(chapter_arg) if chapter_arg.isdigit() else 0
    left_arg = request.args.get("left_version", "0") or "0"
    right_arg = request.args.get("right_version", "0") or "0"
    left_version = int(left_arg) if left_arg.isdigit() else 0
    right_version = int(right_arg) if right_arg.isdigit() else 0
    section_arg = request.args.get("section_id", "0") or "0"
    section_id = int(section_arg) if section_arg.isdigit() else 0
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "run_suggestions":
            service.generate_suggestions()
            message = "Library suggestions refreshed."
        elif action == "restore_version":
            chapter_raw = request.form.get("chapter_id", "0") or "0"
            version_raw = request.form.get("version", "0") or "0"
            chapter_id = int(chapter_raw) if chapter_raw.isdigit() else 0
            version = int(version_raw) if version_raw.isdigit() else 0
            if service.restore_version(chapter_id, version, actor=session.get("user", "ADMIN")):
                message = "Version restored."
            else:
                message = "Could not restore version."
    versions = service.list_versions(chapter_id) if chapter_id else []
    comparison = service.compare_versions(chapter_id, left_version, right_version) if chapter_id and left_version and right_version else None
    sources = service.list_sources(section_id) if section_id else []
    return render_template(
        "admin_library.html",
        suggestions=service.suggestions,
        chapters=service.chapters,
        versions=versions,
        selected_chapter_id=chapter_id,
        comparison=comparison,
        selected_section_id=section_id,
        sources=sources,
        message=message,
    )

