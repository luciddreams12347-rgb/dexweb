from flask import current_app, redirect, render_template, request, session, url_for

from ...database import is_banned
from ...routes import main
from ..auth.session import login_required
from .batches import collect_upload_files
from .permissions import user_is_admin
from .review import normalize_admin_action
from .service import WormJobPermissionError, get_library_service
from .uploads import save_upload


def _public_upload_status(status):
    if status in {"pending", "processing"}:
        return "processing"
    if status in {"processed", "approved", "published", "rejected", "reprocessed"}:
        return "ready"
    if status == "cancelled":
        return "cancelled"
    if status == "worm_failed":
        return "unavailable"
    return "unavailable"


def _public_batch(batch, uploads=None):
    upload_rows = uploads or getattr(batch, "uploads", None) or []
    cancelled_files = sum(1 for upload in upload_rows if upload.get("status") == "cancelled")
    waiting = max(batch.total_files - batch.processed_files - batch.failed_files - cancelled_files, 0)
    if waiting > 0:
        status = "processing"
    elif batch.failed_files and batch.processed_files:
        status = "partial"
    elif batch.failed_files:
        status = "failed"
    else:
        status = "completed"
    return {
        "id": batch.id,
        "title": batch.title,
        "source_type": batch.source_type,
        "total_files": batch.total_files,
        "processed_files": batch.processed_files,
        "waiting_files": waiting,
        "status": status,
    }


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
    username = session.get("user")
    batches = []
    if username:
        for batch in service.list_batches(uploader=username):
            detail = service.get_batch(batch.id)
            uploads = detail.uploads if detail else []
            batches.append(_public_batch(batch, uploads=uploads))
    batch_message = request.args.get("batch_message", "").strip()
    return render_template(
        "library_home.html",
        chapters=chapters,
        viewer_grade=viewer_grade,
        batches=batches,
        batch_message=batch_message,
    )


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
        files = collect_upload_files(request)
        grade_raw = (request.form.get("grade") or "").strip()
        grade = int(grade_raw) if grade_raw.isdigit() else None
        try:
            result = service.process_upload_submission(
                uploader=username,
                file_storages=files,
                grade=grade,
                subject=(request.form.get("subject") or "").strip() or "General",
                title=(request.form.get("title") or "").strip(),
                description=(request.form.get("description") or "").strip(),
                save_upload_fn=save_upload,
            )
            if result["batch"]:
                batch = result["batch"]
                summary = f"{batch.title}: {batch.total_files} uploaded. Processing continues in the background."
                return redirect(url_for("main.library_home", batch_message=summary))
            if result["jobs"]:
                return redirect(
                    url_for(
                        "main.library_home",
                        batch_message="Upload accepted. Processing continues in the background.",
                    )
                )
        except ValueError as error:
            message = str(error)
        except Exception:
            current_app.logger.exception("Library upload failed")
            message = "Upload could not be completed right now."
    return render_template("upload.html", message=message)


@main.route("/library/batch/<int:batch_id>")
def library_batch(batch_id):
    if not login_required():
        return redirect(url_for("main.login"))
    service = get_library_service()
    batch = service.get_batch(batch_id)
    if not batch:
        return render_template("message.html", message="Upload batch not found."), 404
    username = session.get("user")
    if batch.uploader != username and not session.get("is_admin"):
        return render_template("message.html", message="You do not have access to this batch."), 403

    uploads = []
    for upload in batch.uploads:
        item = dict(upload)
        item["public_status"] = _public_upload_status(upload.get("status", "pending"))
        owns_batch = batch.uploader == username
        item["can_cancel"] = upload.get("status") in {"pending", "processing"} and (
            owns_batch or session.get("is_admin")
        )
        uploads.append(item)
    public_batch = _public_batch(batch, uploads=uploads)
    public_batch["uploads"] = uploads
    return render_template("batch_status.html", batch=public_batch)


@main.route("/library/upload/<int:upload_id>/cancel", methods=["POST"])
def library_cancel_upload(upload_id):
    if not login_required():
        return redirect(url_for("main.login"))
    service = get_library_service()
    upload = service._load_upload(upload_id)
    if not upload:
        return render_template("message.html", message="Upload not found."), 404
    username = session.get("user")
    is_admin = user_is_admin()
    if upload.uploader != username and not is_admin:
        return render_template("message.html", message="You do not have access to this upload."), 403
    if upload.status == "cancelled":
        return redirect(f"{request.form.get('next') or url_for('main.library_home')}?batch_message=Upload already cancelled.")
    jobs = service._list_worm_jobs_internal(upload_id=upload_id, statuses=["pending", "processing"], limit=1)
    if not jobs and upload.status in {"pending", "processing"}:
        service._mark_upload_cancelled(upload_id)
        return redirect(f"{request.form.get('next') or url_for('main.library_home')}?batch_message=Upload cancelled.")
    if not jobs:
        return render_template("message.html", message="This upload is no longer processing."), 400
    try:
        result = service.cancel_worm_job(jobs[0].id, actor=username, is_admin=is_admin)
    except WormJobPermissionError:
        return render_template("message.html", message="You do not have permission to cancel this upload."), 403
    redirect_target = request.form.get("next") or url_for("main.library_home")
    if result.get("ok"):
        return redirect(f"{redirect_target}?batch_message={result['message']}")
    return render_template("message.html", message=result.get("message", "Could not cancel upload.")), 400


@main.route("/library/review", methods=["GET", "POST"])
def library_review_queue():
    if not user_is_admin():
        return redirect(url_for("main.admin_login"))
    service = get_library_service()
    message = ""
    if request.method == "POST":
        action = request.form.get("action", "")
        review_raw = request.form.get("review_id", "0") or "0"
        review_id = int(review_raw) if review_raw.isdigit() else 0
        action = normalize_admin_action(action)
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
    return render_template(
        "review_queue.html",
        items=service.list_reviews(),
        message=message,
    )


@main.route("/admin/library/worm", methods=["GET", "POST"])
def admin_worm_jobs():
    if not user_is_admin():
        return redirect(url_for("main.admin_login"))
    service = get_library_service()
    message = ""
    if request.method == "POST":
        action = request.form.get("action", "")
        upload_raw = request.form.get("upload_id", "0") or "0"
        upload_id = int(upload_raw) if upload_raw.isdigit() else 0
        job_raw = request.form.get("job_id", "0") or "0"
        job_id = int(job_raw) if job_raw.isdigit() else 0
        actor = session.get("user", "ADMIN")
        if action == "retry_worm" and upload_id:
            result = service.retry_worm_job(upload_id, actor=actor)
            message = result["message"]
        elif action == "cancel_worm" and job_id:
            result = service.cancel_worm_job(job_id, actor=actor, is_admin=True)
            message = result["message"]
    worm_jobs = service.list_worm_jobs(
        statuses=["pending", "processing", "failed", "cancelled", "completed"],
        limit=100,
        is_admin=True,
    )
    return render_template("admin_worm_jobs.html", worm_jobs=worm_jobs, message=message)


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
