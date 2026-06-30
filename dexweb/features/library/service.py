import json
import threading
from pathlib import Path
from types import SimpleNamespace

from datetime import datetime, timezone

from flask import current_app

from ...database import db_connection, db_cursor, log_action
from ..dex.service import get_dex_service
from .uploads import load_upload_text
from .worm import run_worm_pipeline_timed

_store_lock = threading.Lock()


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _ns(data):
    return SimpleNamespace(**data)


def _to_int(value):
    if value in (None, "", False):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class LibraryService:
    def _db_enabled(self):
        return bool(current_app.config.get("DB_ENABLED"))

    def _store_path(self):
        return Path(current_app.instance_path) / "library_store.json"

    def _empty_store(self):
        return {
            "next_ids": {
                "upload": 1,
                "review": 1,
                "book": 1,
                "chapter": 1,
                "section": 1,
                "version": 1,
                "suggestion": 1,
                "batch": 1,
                "worm_job": 1,
            },
            "uploads": [],
            "batches": [],
            "worm_jobs": [],
            "reviews": [],
            "books": [],
            "chapters": [],
            "sections": [],
            "section_topics": [],
            "versions": [],
            "sources": [],
            "suggestions": [],
        }

    def _load_store(self):
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _store_lock:
            if not path.exists():
                return self._empty_store()
            return json.loads(path.read_text(encoding="utf-8"))

    def _save_store(self, store):
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(store, indent=2)
        temp_path = path.with_suffix(".tmp")
        with _store_lock:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(path)

    def _next_id(self, store, key):
        store["next_ids"].setdefault(key, 1)
        value = store["next_ids"][key]
        store["next_ids"][key] += 1
        return value

    def _load_upload(self, upload_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.id, u.uploader, u.filename, u.stored_path, g.grade_level, s.name, u.title, u.description,
                           u.uploaded_at, u.status, u.original_filename, u.mime_type, u.file_size, u.sha256,
                           u.batch_id, u.folder_path
                    FROM library_uploads u
                    LEFT JOIN library_grades g ON g.id = u.grade_id
                    LEFT JOIN library_subjects s ON s.id = u.subject_id
                    WHERE u.id=%s
                    """,
                    (upload_id,),
                )
                row = cursor.fetchone()
            if not row:
                return None
            return _ns(
                {
                    "id": row[0],
                    "uploader": row[1],
                    "filename": row[2],
                    "stored_path": row[3],
                    "grade": row[4],
                    "subject": row[5] or "General",
                    "title": row[6] or "",
                    "description": row[7] or "",
                    "uploaded_at": row[8],
                    "status": row[9],
                    "original_filename": row[10] or row[2],
                    "mime_type": row[11] or "",
                    "file_size": row[12] or 0,
                    "sha256": row[13] or "",
                    "batch_id": row[14],
                    "folder_path": row[15] or "",
                }
            )
        store = self._load_store()
        row = next((item for item in store["uploads"] if item["id"] == upload_id), None)
        return _ns(row) if row else None

    def _get_or_create_grade(self, cursor, grade_level):
        if grade_level is None:
            return None
        cursor.execute("SELECT id FROM library_grades WHERE grade_level=%s", (grade_level,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute("INSERT INTO library_grades (grade_level) VALUES (%s)", (grade_level,))
        return cursor.lastrowid

    def _get_or_create_subject(self, cursor, name):
        value = (name or "General").strip() or "General"
        cursor.execute("SELECT id FROM library_subjects WHERE name=%s", (value,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute("INSERT INTO library_subjects (name) VALUES (%s)", (value,))
        return cursor.lastrowid

    def _get_or_create_topic(self, cursor, name):
        cursor.execute("SELECT id FROM library_topics WHERE name=%s", (name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute("INSERT INTO library_topics (name) VALUES (%s)", (name,))
        return cursor.lastrowid

    def create_batch(self, uploader, title, source_type, total_files):
        if self._db_enabled():
            with db_connection(autocommit=False) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    INSERT INTO library_upload_batches
                    (uploader, title, source_type, status, total_files, processed_files, failed_files)
                    VALUES (%s, %s, %s, 'processing', %s, 0, 0)
                    """,
                    (uploader, title.strip() or "Upload batch", source_type, total_files),
                )
                batch_id = cursor.lastrowid
                connection.commit()
            return self.get_batch(batch_id)
        store = self._load_store()
        batch_id = self._next_id(store, "batch")
        row = {
            "id": batch_id,
            "uploader": uploader,
            "title": title.strip() or "Upload batch",
            "source_type": source_type,
            "status": "processing",
            "total_files": total_files,
            "processed_files": 0,
            "failed_files": 0,
            "uploaded_at": "now",
            "upload_ids": [],
        }
        store.setdefault("batches", []).append(row)
        self._save_store(store)
        return _ns(row)

    def record_batch_file_result(self, batch_id, success, upload_id=None):
        if not batch_id:
            return
        if self._db_enabled():
            with db_cursor() as cursor:
                if success:
                    cursor.execute(
                        "UPDATE library_upload_batches SET processed_files = processed_files + 1 WHERE id=%s",
                        (batch_id,),
                    )
                else:
                    cursor.execute(
                        "UPDATE library_upload_batches SET failed_files = failed_files + 1 WHERE id=%s",
                        (batch_id,),
                    )
            return
        store = self._load_store()
        batch = next((item for item in store.get("batches", []) if item["id"] == batch_id), None)
        if not batch:
            return
        if success:
            batch["processed_files"] += 1
            if upload_id:
                batch.setdefault("upload_ids", []).append(upload_id)
        else:
            batch["failed_files"] += 1
        self._save_store(store)

    def finalize_batch(self, batch_id):
        if not batch_id:
            return
        batch = self.get_batch(batch_id)
        if not batch:
            return
        finished = batch.processed_files + batch.failed_files
        if batch.failed_files and batch.processed_files:
            status = "partial"
        elif batch.failed_files:
            status = "failed"
        elif finished >= batch.total_files:
            status = "completed"
        else:
            status = "processing"
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute("UPDATE library_upload_batches SET status=%s WHERE id=%s", (status, batch_id))
            return
        store = self._load_store()
        for item in store.get("batches", []):
            if item["id"] == batch_id:
                item["status"] = status
        self._save_store(store)

    def list_batches(self, uploader=None, limit=20):
        if self._db_enabled():
            clauses = []
            params = []
            if uploader:
                clauses.append("uploader=%s")
                params.append(uploader)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with db_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, uploader, title, source_type, status, total_files, processed_files, failed_files, created_at
                    FROM library_upload_batches
                    {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    tuple(params + [limit]),
                )
                rows = cursor.fetchall()
            return [
                _ns(
                    {
                        "id": row[0],
                        "uploader": row[1],
                        "title": row[2],
                        "source_type": row[3],
                        "status": row[4],
                        "total_files": row[5],
                        "processed_files": row[6],
                        "failed_files": row[7],
                        "uploaded_at": row[8],
                    }
                )
                for row in rows
            ]
        store = self._load_store()
        batches = list(store.get("batches", []))
        if uploader:
            batches = [item for item in batches if item["uploader"] == uploader]
        batches.sort(key=lambda item: item["id"], reverse=True)
        return [_ns(item) for item in batches[:limit]]

    def get_batch(self, batch_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, uploader, title, source_type, status, total_files, processed_files, failed_files, created_at
                    FROM library_upload_batches
                    WHERE id=%s
                    """,
                    (batch_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute(
                    """
                    SELECT id, original_filename, folder_path, status
                    FROM library_uploads
                    WHERE batch_id=%s
                    ORDER BY id
                    """,
                    (batch_id,),
                )
                uploads = cursor.fetchall()
            return _ns(
                {
                    "id": row[0],
                    "uploader": row[1],
                    "title": row[2],
                    "source_type": row[3],
                    "status": row[4],
                    "total_files": row[5],
                    "processed_files": row[6],
                    "failed_files": row[7],
                    "uploaded_at": row[8],
                    "uploads": [
                        {"id": item[0], "original_filename": item[1], "folder_path": item[2] or "", "status": item[3]}
                        for item in uploads
                    ],
                }
            )
        store = self._load_store()
        batch = next((item for item in store.get("batches", []) if item["id"] == batch_id), None)
        if not batch:
            return None
        uploads = [item for item in store["uploads"] if item.get("batch_id") == batch_id]
        payload = dict(batch)
        payload["uploads"] = uploads
        return _ns(payload)

    def create_upload(
        self,
        uploader,
        filename,
        stored_path,
        grade,
        subject,
        title,
        description,
        original_filename=None,
        mime_type="",
        file_size=0,
        sha256="",
        batch_id=None,
        folder_path="",
    ):
        if self._db_enabled():
            try:
                with db_connection(autocommit=False) as connection:
                    cursor = connection.cursor()
                    grade_id = self._get_or_create_grade(cursor, grade)
                    subject_id = self._get_or_create_subject(cursor, subject)
                    cursor.execute(
                        """
                        SELECT id FROM library_uploads
                        WHERE uploader=%s AND sha256=%s AND sha256 <> ''
                        """,
                        (uploader, sha256),
                    )
                    duplicate = cursor.fetchone()
                    if duplicate:
                        connection.rollback()
                        raise ValueError("This file was already uploaded.")
                    cursor.execute(
                        """
                        INSERT INTO library_uploads
                        (batch_id, uploader, filename, stored_path, folder_path, title, description, grade_id, subject_id, status,
                         original_filename, mime_type, file_size, sha256)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                        """,
                        (
                            batch_id,
                            uploader,
                            filename,
                            stored_path,
                            folder_path or None,
                            title.strip(),
                            description.strip(),
                            grade_id,
                            subject_id,
                            original_filename or filename,
                            mime_type,
                            file_size,
                            sha256,
                        ),
                    )
                    upload_id = cursor.lastrowid
                    connection.commit()
                return self._load_upload(upload_id)
            except Exception:
                current_app.logger.exception("Library upload creation failed")
                raise
        store = self._load_store()
        if sha256 and any(item["uploader"] == uploader and item.get("sha256") == sha256 for item in store["uploads"]):
            raise ValueError("This file was already uploaded.")
        upload_id = self._next_id(store, "upload")
        row = {
            "id": upload_id,
            "batch_id": batch_id,
            "uploader": uploader,
            "filename": filename,
            "stored_path": stored_path,
            "folder_path": folder_path or "",
            "grade": grade,
            "subject": subject.strip() or "General",
            "title": title.strip(),
            "description": description.strip(),
            "uploaded_at": "now",
            "status": "pending",
            "original_filename": original_filename or filename,
            "mime_type": mime_type,
            "file_size": file_size,
            "sha256": sha256,
        }
        store["uploads"].append(row)
        self._save_store(store)
        return _ns(row)

    def _worm_timeout_seconds(self):
        return int(current_app.config.get("WORM_AI_TIMEOUT", 120))

    def create_worm_job(self, upload_id):
        if self._db_enabled():
            with db_connection(autocommit=False) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    INSERT INTO library_worm_jobs (upload_id, status)
                    VALUES (%s, 'pending')
                    """,
                    (upload_id,),
                )
                job_id = cursor.lastrowid
                connection.commit()
            return self.get_worm_job(job_id)
        store = self._load_store()
        job_id = self._next_id(store, "worm_job")
        row = {
            "id": job_id,
            "upload_id": upload_id,
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "error_message": None,
            "created_at": _utcnow_iso(),
        }
        store.setdefault("worm_jobs", []).append(row)
        self._save_store(store)
        return _ns(row)

    def get_worm_job(self, job_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.id, j.upload_id, j.status, j.started_at, j.completed_at, j.error_message, j.created_at,
                           u.original_filename, u.filename, u.uploader, u.batch_id
                    FROM library_worm_jobs j
                    JOIN library_uploads u ON u.id = j.upload_id
                    WHERE j.id=%s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
            if not row:
                return None
            return _ns(
                {
                    "id": row[0],
                    "upload_id": row[1],
                    "status": row[2],
                    "started_at": row[3],
                    "completed_at": row[4],
                    "error_message": row[5],
                    "created_at": row[6],
                    "source_file": row[7] or row[8],
                    "uploader": row[9],
                    "batch_id": row[10],
                }
            )
        store = self._load_store()
        job = next((item for item in store.get("worm_jobs", []) if item["id"] == job_id), None)
        if not job:
            return None
        upload = next((item for item in store["uploads"] if item["id"] == job["upload_id"]), None)
        payload = dict(job)
        if upload:
            payload["source_file"] = upload.get("original_filename") or upload.get("filename")
            payload["uploader"] = upload.get("uploader")
            payload["batch_id"] = upload.get("batch_id")
        return _ns(payload)

    def get_worm_job_for_upload(self, upload_id):
        jobs = self.list_worm_jobs(upload_id=upload_id, limit=1)
        return jobs[0] if jobs else None

    def list_worm_jobs(self, statuses=None, upload_id=None, limit=50):
        statuses = statuses or []
        if self._db_enabled():
            clauses = []
            params = []
            if statuses:
                placeholders = ", ".join(["%s"] * len(statuses))
                clauses.append(f"j.status IN ({placeholders})")
                params.extend(statuses)
            if upload_id:
                clauses.append("j.upload_id=%s")
                params.append(upload_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with db_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT j.id, j.upload_id, j.status, j.started_at, j.completed_at, j.error_message, j.created_at,
                           u.original_filename, u.filename, u.uploader
                    FROM library_worm_jobs j
                    JOIN library_uploads u ON u.id = j.upload_id
                    {where}
                    ORDER BY j.created_at DESC, j.id DESC
                    LIMIT %s
                    """,
                    tuple(params + [limit]),
                )
                rows = cursor.fetchall()
            return [
                _ns(
                    {
                        "id": row[0],
                        "upload_id": row[1],
                        "status": row[2],
                        "started_at": row[3],
                        "completed_at": row[4],
                        "error_message": row[5],
                        "created_at": row[6],
                        "source_file": row[7] or row[8],
                        "uploader": row[9],
                    }
                )
                for row in rows
            ]
        store = self._load_store()
        jobs = list(store.get("worm_jobs", []))
        if statuses:
            jobs = [item for item in jobs if item.get("status") in statuses]
        if upload_id:
            jobs = [item for item in jobs if item.get("upload_id") == upload_id]
        jobs.sort(key=lambda item: item["id"], reverse=True)
        uploads = {item["id"]: item for item in store["uploads"]}
        out = []
        for job in jobs[:limit]:
            payload = dict(job)
            upload = uploads.get(job["upload_id"])
            if upload:
                payload["source_file"] = upload.get("original_filename") or upload.get("filename")
                payload["uploader"] = upload.get("uploader")
            out.append(_ns(payload))
        return out

    def update_worm_job(self, job_id, status=None, started_at=None, completed_at=None, error_message=None):
        if self._db_enabled():
            fields = []
            params = []
            if status is not None:
                fields.append("status=%s")
                params.append(status)
            if started_at is not None:
                fields.append("started_at=%s")
                params.append(started_at)
            if completed_at is not None:
                fields.append("completed_at=%s")
                params.append(completed_at)
            if error_message is not None:
                fields.append("error_message=%s")
                params.append(error_message)
            if not fields:
                return
            params.append(job_id)
            with db_cursor() as cursor:
                cursor.execute(f"UPDATE library_worm_jobs SET {', '.join(fields)} WHERE id=%s", tuple(params))
            return
        store = self._load_store()
        for job in store.get("worm_jobs", []):
            if job["id"] == job_id:
                if status is not None:
                    job["status"] = status
                if started_at is not None:
                    job["started_at"] = started_at
                if completed_at is not None:
                    job["completed_at"] = completed_at
                if error_message is not None:
                    job["error_message"] = error_message
        self._save_store(store)

    def schedule_worm_job(self, upload_id):
        job = self.create_worm_job(upload_id)
        from .worm_worker import get_worm_worker

        get_worm_worker().enqueue(upload_id, job.id, current_app._get_current_object())
        return job

    def resume_pending_worm_jobs(self, enqueue_fn):
        jobs = self.list_worm_jobs(statuses=["pending", "processing"], limit=500)
        for job in jobs:
            if job.status == "processing":
                self.update_worm_job(job.id, status="pending", started_at=None)
            enqueue_fn(job.upload_id, job.id)

    def retry_worm_job(self, upload_id, actor="ADMIN"):
        upload = self._load_upload(upload_id)
        if not upload:
            return {"ok": False, "message": "Upload not found."}
        job = self.schedule_worm_job(upload_id)
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute("UPDATE library_uploads SET status='pending' WHERE id=%s", (upload_id,))
        else:
            store = self._load_store()
            for item in store["uploads"]:
                if item["id"] == upload_id:
                    item["status"] = "pending"
            self._save_store(store)
        log_action(actor, f"Library worm retry scheduled upload_id={upload_id} job_id={job.id}")
        return {"ok": True, "message": f"Worm retry queued for upload #{upload_id}.", "job_id": job.id}

    def execute_worm_job(self, upload_id, job_id):
        job = self.get_worm_job(job_id)
        if not job or job.upload_id != upload_id:
            return None
        if job.status == "completed":
            return self.get_review_for_upload(upload_id)
        self.update_worm_job(job_id, status="processing", started_at=_utcnow_iso(), error_message=None)
        upload = self._load_upload(upload_id)
        if not upload:
            self._fail_worm_job(job_id, upload_id, "Upload not found.")
            return None
        try:
            extracted_text = load_upload_text(upload.stored_path)
            processed = run_worm_pipeline_timed(
                get_dex_service(),
                upload,
                extracted_text,
                self._worm_timeout_seconds(),
            )
            review = self._create_review_from_processed(upload_id, upload, processed)
            self.update_worm_job(job_id, status="completed", completed_at=_utcnow_iso(), error_message=None)
            self._mark_upload_processed(upload_id)
            self.record_batch_file_result(getattr(upload, "batch_id", None), success=True, upload_id=upload_id)
            if getattr(upload, "batch_id", None):
                self._maybe_finalize_batch(upload.batch_id)
            log_action(upload.uploader, f"Library worm completed upload_id={upload_id} review_id={review.id}")
            return review
        except Exception as error:
            current_app.logger.exception("Library worm job failed upload_id=%s job_id=%s", upload_id, job_id)
            message = str(error) or "Worm could not process this upload right now."
            self._fail_worm_job(job_id, upload_id, message)
            log_action(upload.uploader, f"Library worm processing failure upload_id={upload_id}")
            return None

    def _fail_worm_job(self, job_id, upload_id, message):
        self.update_worm_job(job_id, status="failed", completed_at=_utcnow_iso(), error_message=message)
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute("UPDATE library_uploads SET status='worm_failed' WHERE id=%s", (upload_id,))
        else:
            store = self._load_store()
            for item in store["uploads"]:
                if item["id"] == upload_id:
                    item["status"] = "worm_failed"
            self._save_store(store)
        upload = self._load_upload(upload_id)
        batch_id = upload.batch_id if upload else None
        self.record_batch_file_result(batch_id, success=False)
        if batch_id:
            self._maybe_finalize_batch(batch_id)

    def _mark_upload_processed(self, upload_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute("UPDATE library_uploads SET status='processed' WHERE id=%s", (upload_id,))
            return
        store = self._load_store()
        for item in store["uploads"]:
            if item["id"] == upload_id:
                item["status"] = "processed"
        self._save_store(store)

    def _maybe_finalize_batch(self, batch_id):
        batch = self.get_batch(batch_id)
        if not batch:
            return
        finished = batch.processed_files + batch.failed_files
        if finished >= batch.total_files:
            self.finalize_batch(batch_id)

    def get_review_for_upload(self, upload_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM library_review_queue WHERE upload_id=%s ORDER BY id DESC LIMIT 1",
                    (upload_id,),
                )
                row = cursor.fetchone()
            return self.get_review(row[0]) if row else None
        store = self._load_store()
        review = next((item for item in reversed(store["reviews"]) if item["upload_id"] == upload_id), None)
        return _ns(review) if review else None

    def _create_review_from_processed(self, upload_id, upload, processed):
        if self._db_enabled():
            with db_connection(autocommit=False) as connection:
                cursor = connection.cursor()
                grade_id = self._get_or_create_grade(cursor, processed["detected_grade"])
                subject_id = self._get_or_create_subject(cursor, processed["detected_subject"])
                cursor.execute(
                    """
                    INSERT INTO library_review_queue
                    (upload_id, extracted_text, detected_subject_id, detected_grade_id, suggested_chapter, suggested_section, confidence, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                    """,
                    (
                        upload_id,
                        processed["extracted_text"],
                        subject_id,
                        grade_id,
                        processed["suggested_chapter"],
                        processed["suggested_section"],
                        processed["confidence"],
                    ),
                )
                review_id = cursor.lastrowid
                for topic in processed["detected_topics"]:
                    topic_id = self._get_or_create_topic(cursor, topic)
                    cursor.execute(
                        "INSERT INTO library_review_topics (review_id, topic_id) VALUES (%s, %s)",
                        (review_id, topic_id),
                    )
                connection.commit()
            return self.get_review(review_id)

        store = self._load_store()
        review_id = self._next_id(store, "review")
        store["reviews"].append(
            {
                "id": review_id,
                "upload_id": upload_id,
                "extracted_text": processed["extracted_text"],
                "detected_subject": processed["detected_subject"],
                "detected_grade": processed["detected_grade"],
                "detected_topics": processed["detected_topics"],
                "suggested_chapter": processed["suggested_chapter"],
                "suggested_section": processed["suggested_section"],
                "confidence": processed["confidence"],
                "ai_suggestions": processed.get("ai_suggestions", {}),
                "source_file": upload.original_filename if hasattr(upload, "original_filename") else upload.filename,
                "status": "pending",
                "created_at": "now",
            }
        )
        self._save_store(store)
        return self.get_review(review_id)

    def process_upload_submission(self, uploader, file_storages, grade, subject, title, description, save_upload_fn):
        from .batches import batch_title_from_files, detect_source_type, folder_path_for_file

        if not file_storages:
            raise ValueError("Select a file to upload.")
        source_type = detect_source_type(file_storages)
        use_batch = source_type in {"multi", "folder"}
        batch = None
        if use_batch:
            batch = self.create_batch(
                uploader=uploader,
                title=batch_title_from_files(file_storages, title),
                source_type=source_type,
                total_files=len(file_storages),
            )
        processed_reviews = []
        queued_jobs = []
        errors = []
        for file_storage in file_storages:
            upload_meta = None
            folder_path = folder_path_for_file(file_storage)
            try:
                upload_meta = save_upload_fn(file_storage)
                upload = self.create_upload(
                    uploader=uploader,
                    filename=upload_meta["stored_filename"],
                    stored_path=upload_meta["stored_path"],
                    grade=grade,
                    subject=subject,
                    title=title,
                    description=description,
                    original_filename=upload_meta["original_filename"],
                    mime_type=upload_meta["mime_type"],
                    file_size=upload_meta["file_size"],
                    sha256=upload_meta["sha256"],
                    batch_id=batch.id if batch else None,
                    folder_path=upload_meta.get("folder_path") or folder_path,
                )
                job = self.schedule_worm_job(upload.id)
                queued_jobs.append(job)
                log_action(
                    uploader,
                    f"Uploaded library source file={upload_meta['original_filename']} worm_job_id={job.id}"
                    + (f" batch_id={batch.id}" if batch else ""),
                )
            except ValueError as error:
                if upload_meta:
                    try:
                        Path(upload_meta["stored_path"]).unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception("Could not remove failed upload")
                errors.append(str(error))
                self.record_batch_file_result(batch.id if batch else None, success=False)
            except Exception:
                if upload_meta:
                    try:
                        Path(upload_meta["stored_path"]).unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception("Could not remove failed upload")
                current_app.logger.exception("Library upload failed")
                errors.append("Upload could not be completed right now.")
                self.record_batch_file_result(batch.id if batch else None, success=False)
        if not queued_jobs and errors:
            if batch:
                self.finalize_batch(batch.id)
            if len(errors) == 1:
                raise ValueError(errors[0])
            raise ValueError("; ".join(errors))
        return {
            "batch": batch,
            "jobs": queued_jobs,
            "reviews": processed_reviews,
            "errors": errors,
        }

    def run_worm(self, upload_id):
        job = self.schedule_worm_job(upload_id)
        from .worm_worker import get_worm_worker

        get_worm_worker().drain(timeout=10)
        review = self.get_review_for_upload(upload_id)
        if review:
            return review
        job = self.get_worm_job(job.id)
        if job and job.status == "failed":
            raise ValueError(job.error_message or "Worm could not process this upload right now.")
        raise ValueError("Worm could not process this upload right now.")

    def list_reviews(self):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.id, r.upload_id, r.extracted_text, s.name, g.grade_level, r.suggested_chapter,
                           r.suggested_section, r.confidence, u.filename, r.status, r.created_at
                    FROM library_review_queue r
                    JOIN library_uploads u ON u.id = r.upload_id
                    LEFT JOIN library_subjects s ON s.id = r.detected_subject_id
                    LEFT JOIN library_grades g ON g.id = r.detected_grade_id
                    ORDER BY r.created_at DESC, r.id DESC
                    """
                )
                rows = cursor.fetchall()
                review_ids = [row[0] for row in rows]
                topics = {}
                if review_ids:
                    placeholders = ", ".join(["%s"] * len(review_ids))
                    cursor.execute(
                        f"""
                        SELECT rt.review_id, t.name
                        FROM library_review_topics rt
                        JOIN library_topics t ON t.id = rt.topic_id
                        WHERE rt.review_id IN ({placeholders})
                        ORDER BY t.name
                        """,
                        tuple(review_ids),
                    )
                    for review_id, topic_name in cursor.fetchall():
                        topics.setdefault(review_id, []).append(topic_name)
            return [
                _ns(
                    {
                        "id": row[0],
                        "upload_id": row[1],
                        "extracted_text": row[2],
                        "detected_subject": row[3] or "General",
                        "detected_grade": row[4],
                        "detected_topics": topics.get(row[0], []),
                        "suggested_chapter": row[5],
                        "suggested_section": row[6],
                        "confidence": float(row[7]),
                        "source_file": row[8],
                        "status": row[9],
                        "created_at": row[10],
                        "ai_suggestions": {
                            "subject": row[3] or "General",
                            "grade": row[4],
                            "suggested_chapter": row[5],
                            "suggested_section": row[6],
                            "confidence": float(row[7]),
                            "topics": topics.get(row[0], []),
                        },
                    }
                )
                for row in rows
            ]
        store = self._load_store()
        return [_ns(item) for item in reversed(store["reviews"])]

    def get_review(self, review_id):
        return next((item for item in self.list_reviews() if item.id == review_id), None)

    def _find_book_and_chapter(self, cursor, grade, subject, chapter_title):
        cursor.execute(
            """
            SELECT c.id, b.id
            FROM library_chapters c
            JOIN library_books b ON b.id = c.book_id
            JOIN library_grades g ON g.id = b.grade_id
            JOIN library_subjects s ON s.id = b.subject_id
            WHERE g.grade_level <=> %s AND s.name=%s AND c.title=%s
            LIMIT 1
            """,
            (grade, subject, chapter_title),
        )
        return cursor.fetchone()

    def _snapshot_chapter_db(self, cursor, chapter_id, actor):
        cursor.execute(
            """
            SELECT c.id, c.title, c.sequence_num, b.is_published, b.title, g.grade_level, s.name
            FROM library_chapters c
            JOIN library_books b ON b.id = c.book_id
            JOIN library_grades g ON g.id = b.grade_id
            JOIN library_subjects s ON s.id = b.subject_id
            WHERE c.id=%s
            """,
            (chapter_id,),
        )
        row = cursor.fetchone()
        cursor.execute(
            """
            SELECT id, title, content, sequence_num
            FROM library_sections
            WHERE chapter_id=%s
            ORDER BY sequence_num, id
            """,
            (chapter_id,),
        )
        sections = cursor.fetchall()
        section_ids = [item[0] for item in sections]
        topics_map = {}
        sources_map = {}
        if section_ids:
            placeholders = ", ".join(["%s"] * len(section_ids))
            cursor.execute(
                f"""
                SELECT st.section_id, t.name
                FROM library_section_topics st
                JOIN library_topics t ON t.id = st.topic_id
                WHERE st.section_id IN ({placeholders})
                ORDER BY t.name
                """,
                tuple(section_ids),
            )
            for section_id, topic_name in cursor.fetchall():
                topics_map.setdefault(section_id, []).append(topic_name)
            cursor.execute(
                f"""
                SELECT src.section_id, src.upload_id, u.filename, u.uploader, u.uploaded_at, src.source_location
                FROM library_sources src
                JOIN library_uploads u ON u.id = src.upload_id
                WHERE src.section_id IN ({placeholders})
                ORDER BY src.id
                """,
                tuple(section_ids),
            )
            for section_id, upload_id, filename, uploader, uploaded_at, source_location in cursor.fetchall():
                sources_map.setdefault(section_id, []).append(
                    {
                        "upload_id": upload_id,
                        "filename": filename,
                        "uploader": uploader,
                        "uploaded_at": str(uploaded_at),
                        "location": source_location,
                    }
                )
        cursor.execute("SELECT COALESCE(MAX(version_number), 0) + 1 FROM library_versions WHERE chapter_id=%s", (chapter_id,))
        version_number = cursor.fetchone()[0]
        snapshot = {
            "chapter": {
                "id": row[0],
                "title": row[1],
                "sequence_num": row[2],
                "published": bool(row[3]),
                "book_title": row[4],
                "grade": row[5],
                "subject": row[6],
            },
            "sections": [
                {
                    "id": item[0],
                    "title": item[1],
                    "content": item[2],
                    "sequence_num": item[3],
                    "topics": topics_map.get(item[0], []),
                    "sources": sources_map.get(item[0], []),
                }
                for item in sections
            ],
        }
        cursor.execute(
            """
            INSERT INTO library_versions (chapter_id, version_number, changed_by, snapshot_json)
            VALUES (%s, %s, %s, %s)
            """,
            (chapter_id, version_number, actor, json.dumps(snapshot)),
        )

    def apply_review_action(self, review_id, action, actor, edits):
        item = self.get_review(review_id)
        if not item:
            return {"ok": False, "message": "Review item not found."}

        if action == "reject":
            if self._db_enabled():
                with db_cursor() as cursor:
                    cursor.execute("UPDATE library_review_queue SET status='rejected' WHERE id=%s", (review_id,))
                    cursor.execute("UPDATE library_uploads SET status='rejected' WHERE id=%s", (item.upload_id,))
                log_action(actor, f"Library review rejected review_id={review_id}")
                return {"ok": True, "message": "Review item rejected."}
            store = self._load_store()
            for review in store["reviews"]:
                if review["id"] == review_id:
                    review["status"] = "rejected"
            self._save_store(store)
            return {"ok": True, "message": "Review item rejected."}

        if action == "reprocess":
            if self._db_enabled():
                with db_cursor() as cursor:
                    cursor.execute("UPDATE library_review_queue SET status='reprocessed' WHERE id=%s", (review_id,))
            else:
                store = self._load_store()
                for review in store["reviews"]:
                    if review["id"] == review_id:
                        review["status"] = "reprocessed"
                self._save_store(store)
            result = self.retry_worm_job(item.upload_id, actor=actor)
            get_worm_worker = __import__("dexweb.features.library.worm_worker", fromlist=["get_worm_worker"]).get_worm_worker
            get_worm_worker().drain(timeout=10)
            refreshed = self.get_review_for_upload(item.upload_id)
            if refreshed:
                return {"ok": True, "message": f"Reprocessed as review #{refreshed.id}."}
            return result

        chapter_title = (edits.get("chapter_title") or item.suggested_chapter).strip() or item.suggested_chapter
        section_title = (edits.get("section_title") or item.suggested_section).strip() or item.suggested_section
        subject = (edits.get("subject") or item.detected_subject or "General").strip() or "General"
        grade = _to_int(edits.get("grade"))
        if grade is None:
            grade = item.detected_grade
        content = (edits.get("content") or item.extracted_text).strip() or item.extracted_text
        topics = [t.strip() for t in (edits.get("topics") or ",".join(item.detected_topics)).split(",") if t.strip()]

        if self._db_enabled():
            try:
                with db_connection(autocommit=False) as connection:
                    cursor = connection.cursor()
                    upload = self._load_upload(item.upload_id)
                    grade_id = self._get_or_create_grade(cursor, grade)
                    subject_id = self._get_or_create_subject(cursor, subject)
                    found = None
                    target_chapter_id = _to_int(edits.get("chapter_id"))
                    if target_chapter_id:
                        cursor.execute("SELECT id, book_id FROM library_chapters WHERE id=%s", (target_chapter_id,))
                        found = cursor.fetchone()
                    if not found:
                        found = self._find_book_and_chapter(cursor, grade, subject, chapter_title)
                    if found:
                        chapter_id, book_id = found
                        cursor.execute(
                            "UPDATE library_books SET grade_id=%s, subject_id=%s, title=%s WHERE id=%s",
                            (grade_id, subject_id, chapter_title, book_id),
                        )
                        cursor.execute("UPDATE library_chapters SET title=%s WHERE id=%s", (chapter_title, chapter_id))
                    else:
                        cursor.execute(
                            """
                            INSERT INTO library_books (grade_id, subject_id, title, is_published)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (grade_id, subject_id, chapter_title, 1 if action in {"approve", "publish"} else 0),
                        )
                        book_id = cursor.lastrowid
                        cursor.execute("INSERT INTO library_chapters (book_id, title, sequence_num) VALUES (%s, %s, 1)", (book_id, chapter_title))
                        chapter_id = cursor.lastrowid
                    if action in {"approve", "publish"}:
                        cursor.execute("UPDATE library_books SET is_published=1 WHERE id=%s", (book_id,))
                    elif action == "unpublish":
                        cursor.execute("UPDATE library_books SET is_published=0 WHERE id=%s", (book_id,))

                    cursor.execute("SELECT COALESCE(MAX(sequence_num), 0) + 1 FROM library_sections WHERE chapter_id=%s", (chapter_id,))
                    sequence_num = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO library_sections (chapter_id, title, content, sequence_num)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (chapter_id, section_title, content, sequence_num),
                    )
                    section_id = cursor.lastrowid
                    for topic in topics:
                        topic_id = self._get_or_create_topic(cursor, topic)
                        cursor.execute("INSERT INTO library_section_topics (section_id, topic_id) VALUES (%s, %s)", (section_id, topic_id))
                    cursor.execute(
                        "INSERT INTO library_sources (section_id, upload_id, source_location) VALUES (%s, %s, %s)",
                        (section_id, item.upload_id, "full-document"),
                    )
                    review_status = "approved" if action == "approve" else action
                    cursor.execute("UPDATE library_review_queue SET status=%s WHERE id=%s", (review_status, review_id))
                    cursor.execute("UPDATE library_uploads SET status=%s WHERE id=%s", (review_status, item.upload_id))
                    self._snapshot_chapter_db(cursor, chapter_id, actor)
                    connection.commit()
                log_action(actor, f"Library review action={action} review_id={review_id} section_id={section_id}")
                return {"ok": True, "message": f"Action '{action}' applied.", "chapter_id": chapter_id, "section_id": section_id}
            except Exception:
                current_app.logger.exception("Library review action failed")
                return {"ok": False, "message": "Could not update the review item."}

        store = self._load_store()
        upload = next((row for row in store["uploads"] if row["id"] == item.upload_id), None)
        target_chapter_id = _to_int(edits.get("chapter_id"))
        chapter = None
        if target_chapter_id:
            chapter = next((row for row in store["chapters"] if row["id"] == target_chapter_id), None)
        if not chapter:
            chapter = next(
                (row for row in store["chapters"] if row["title"].lower() == chapter_title.lower() and row["subject"].lower() == subject.lower()),
                None,
            )
        if not chapter:
            book_id = self._next_id(store, "book")
            store["books"].append({"id": book_id, "grade": grade, "subject": subject, "title": chapter_title, "published": action in {"approve", "publish"}})
            chapter = {"id": self._next_id(store, "chapter"), "book_id": book_id, "title": chapter_title, "subject": subject, "grade": grade}
            store["chapters"].append(chapter)
        book = next((row for row in store["books"] if row["id"] == chapter["book_id"]), None)
        if book:
            book["grade"] = grade
            book["subject"] = subject
            book["title"] = chapter_title
            if action in {"approve", "publish"}:
                book["published"] = True
            elif action == "unpublish":
                book["published"] = False
        section_id = self._next_id(store, "section")
        store["sections"].append(
            {"id": section_id, "chapter_id": chapter["id"], "title": section_title, "content": content, "sequence_num": 1, "topics": topics}
        )
        store["sources"].append({"section_id": section_id, "upload_id": item.upload_id, "source_location": "full-document"})
        version_id = self._next_id(store, "version")
        chapter_sections = [row for row in store["sections"] if row["chapter_id"] == chapter["id"]]
        store["versions"].append(
            {
                "id": version_id,
                "chapter_id": chapter["id"],
                "version": len([row for row in store["versions"] if row["chapter_id"] == chapter["id"]]) + 1,
                "actor": actor,
                "snapshot": {"chapter": chapter, "sections": chapter_sections},
            }
        )
        for review in store["reviews"]:
            if review["id"] == review_id:
                review["status"] = "approved" if action == "approve" else action
        self._save_store(store)
        return {"ok": True, "message": f"Action '{action}' applied.", "chapter_id": chapter["id"], "section_id": section_id}

    def list_public_chapters(self):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.id, g.grade_level, s.name, c.title
                    FROM library_chapters c
                    JOIN library_books b ON b.id = c.book_id
                    JOIN library_grades g ON g.id = b.grade_id
                    JOIN library_subjects s ON s.id = b.subject_id
                    WHERE b.is_published=1
                    ORDER BY g.grade_level, s.name, c.title
                    """
                )
                rows = cursor.fetchall()
            return [{"id": row[0], "grade": row[1], "subject": row[2], "title": row[3]} for row in rows]
        store = self._load_store()
        out = []
        for chapter in store["chapters"]:
            book = next((row for row in store["books"] if row["id"] == chapter["book_id"]), None)
            if book and book.get("published"):
                out.append({"id": chapter["id"], "grade": book.get("grade"), "subject": book.get("subject"), "title": chapter["title"]})
        return out

    def chapter_view(self, chapter_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.id, c.title, g.grade_level, s.name
                    FROM library_chapters c
                    JOIN library_books b ON b.id = c.book_id
                    JOIN library_grades g ON g.id = b.grade_id
                    JOIN library_subjects s ON s.id = b.subject_id
                    WHERE c.id=%s AND b.is_published=1
                    """,
                    (chapter_id,),
                )
                chapter_row = cursor.fetchone()
                if not chapter_row:
                    return None
                cursor.execute(
                    """
                    SELECT sec.id, sec.title, sec.content
                    FROM library_sections sec
                    WHERE sec.chapter_id=%s
                    ORDER BY sec.sequence_num, sec.id
                    """,
                    (chapter_id,),
                )
                section_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT rc.id, rc.title
                    FROM library_chapters rc
                    JOIN library_books rb ON rb.id = rc.book_id
                    JOIN library_books cb ON cb.id = (SELECT book_id FROM library_chapters WHERE id=%s)
                    JOIN library_subjects rs ON rs.id = rb.subject_id
                    JOIN library_subjects cs ON cs.id = cb.subject_id
                    WHERE rc.id <> %s AND rb.is_published=1 AND rs.name = cs.name
                    ORDER BY rc.id DESC LIMIT 5
                    """,
                    (chapter_id, chapter_id),
                )
                related_rows = cursor.fetchall()
            return {
                "chapter": {"id": chapter_row[0], "title": chapter_row[1], "grade": chapter_row[2], "subject": chapter_row[3]},
                "sections": [{"id": row[0], "title": row[1], "content": row[2]} for row in section_rows],
                "related": [{"id": row[0], "title": row[1]} for row in related_rows],
            }
        store = self._load_store()
        chapter = next((row for row in store["chapters"] if row["id"] == chapter_id), None)
        if not chapter:
            return None
        book = next((row for row in store["books"] if row["id"] == chapter["book_id"]), None)
        if not book or not book.get("published"):
            return None
        sections = [row for row in store["sections"] if row["chapter_id"] == chapter_id]
        related = [
            {"id": row["id"], "title": row["title"]}
            for row in store["chapters"]
            if row["id"] != chapter_id and next((b for b in store["books"] if b["id"] == row["book_id"] and b.get("subject") == book.get("subject") and b.get("published")), None)
        ][:5]
        return {"chapter": {"id": chapter_id, "title": chapter["title"], "grade": book.get("grade"), "subject": book.get("subject")}, "sections": sections, "related": related}

    def search_public(self, grade=None, subject=None, topic=None, keyword=None):
        if self._db_enabled():
            clauses = ["b.is_published=1"]
            params = []
            if grade is not None:
                clauses.append("g.grade_level=%s")
                params.append(grade)
            if subject:
                clauses.append("LOWER(s.name)=LOWER(%s)")
                params.append(subject)
            if keyword:
                clauses.append("(LOWER(sec.title) LIKE LOWER(%s) OR LOWER(sec.content) LIKE LOWER(%s) OR LOWER(c.title) LIKE LOWER(%s))")
                pattern = f"%{keyword}%"
                params.extend([pattern, pattern, pattern])
            if topic:
                clauses.append(
                    """
                    EXISTS (
                        SELECT 1 FROM library_section_topics st
                        JOIN library_topics t ON t.id = st.topic_id
                        WHERE st.section_id = sec.id AND LOWER(t.name) LIKE LOWER(%s)
                    )
                    """
                )
                params.append(f"%{topic}%")
            with db_cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT sec.id, sec.title, sec.content, c.title, g.grade_level, s.name
                    FROM library_sections sec
                    JOIN library_chapters c ON c.id = sec.chapter_id
                    JOIN library_books b ON b.id = c.book_id
                    JOIN library_grades g ON g.id = b.grade_id
                    JOIN library_subjects s ON s.id = b.subject_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY g.grade_level, s.name, c.title, sec.sequence_num
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall()
            return [
                {"id": row[0], "title": row[1], "content": row[2], "chapter_title": row[3], "grade": row[4], "subject": row[5]}
                for row in rows
            ]
        results = []
        for chapter in self.list_public_chapters():
            view = self.chapter_view(chapter["id"])
            for section in view["sections"]:
                text = " ".join([chapter["title"], section["title"], section["content"], " ".join(section.get("topics", []))]).lower()
                if grade is not None and chapter["grade"] != grade:
                    continue
                if subject and chapter["subject"].lower() != subject.lower():
                    continue
                if topic and topic.lower() not in text:
                    continue
                if keyword and keyword.lower() not in text:
                    continue
                results.append(
                    {
                        "id": section["id"],
                        "title": section["title"],
                        "content": section["content"],
                        "chapter_title": chapter["title"],
                        "grade": chapter["grade"],
                        "subject": chapter["subject"],
                    }
                )
        return results

    def list_versions(self, chapter_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT version_number, changed_by, created_at, snapshot_json
                    FROM library_versions
                    WHERE chapter_id=%s
                    ORDER BY version_number DESC
                    """,
                    (chapter_id,),
                )
                rows = cursor.fetchall()
            return [
                {"version": row[0], "actor": row[1], "created_at": row[2], "snapshot": json.loads(row[3])}
                for row in rows
            ]
        store = self._load_store()
        versions = [row for row in store["versions"] if row["chapter_id"] == chapter_id]
        versions.sort(key=lambda item: item["version"], reverse=True)
        return versions

    def compare_versions(self, chapter_id, left_version, right_version):
        versions = {item["version"]: item for item in self.list_versions(chapter_id)}
        left = versions.get(left_version)
        right = versions.get(right_version)
        if not left or not right:
            return None
        left_sections = left["snapshot"]["sections"]
        right_sections = right["snapshot"]["sections"]
        return {
            "left": left,
            "right": right,
            "summary": f"Sections: {len(left_sections)} -> {len(right_sections)}",
        }

    def restore_version(self, chapter_id, version_number, actor):
        if self._db_enabled():
            try:
                with db_connection(autocommit=False) as connection:
                    cursor = connection.cursor()
                    cursor.execute(
                        "SELECT snapshot_json FROM library_versions WHERE chapter_id=%s AND version_number=%s",
                        (chapter_id, version_number),
                    )
                    row = cursor.fetchone()
                    if not row:
                        connection.rollback()
                        return False
                    snapshot = json.loads(row[0])
                    cursor.execute("SELECT id FROM library_sections WHERE chapter_id=%s", (chapter_id,))
                    existing_section_ids = [item[0] for item in cursor.fetchall()]
                    if existing_section_ids:
                        placeholders = ", ".join(["%s"] * len(existing_section_ids))
                        cursor.execute(f"DELETE FROM library_sources WHERE section_id IN ({placeholders})", tuple(existing_section_ids))
                        cursor.execute(f"DELETE FROM library_section_topics WHERE section_id IN ({placeholders})", tuple(existing_section_ids))
                    cursor.execute("DELETE FROM library_sections WHERE chapter_id=%s", (chapter_id,))
                    cursor.execute("UPDATE library_chapters SET title=%s WHERE id=%s", (snapshot["chapter"]["title"], chapter_id))
                    cursor.execute(
                        """
                        UPDATE library_books b
                        JOIN library_chapters c ON c.book_id = b.id
                        JOIN library_grades g ON g.id = b.grade_id
                        JOIN library_subjects s ON s.id = b.subject_id
                        SET b.is_published=%s
                        WHERE c.id=%s
                        """,
                        (1 if snapshot["chapter"]["published"] else 0, chapter_id),
                    )
                    for section in snapshot["sections"]:
                        cursor.execute(
                            "INSERT INTO library_sections (chapter_id, title, content, sequence_num) VALUES (%s, %s, %s, %s)",
                            (chapter_id, section["title"], section["content"], section.get("sequence_num", 1)),
                        )
                        new_section_id = cursor.lastrowid
                        for topic in section.get("topics", []):
                            topic_id = self._get_or_create_topic(cursor, topic)
                            cursor.execute("INSERT INTO library_section_topics (section_id, topic_id) VALUES (%s, %s)", (new_section_id, topic_id))
                        for source in section.get("sources", []):
                            cursor.execute(
                                "INSERT INTO library_sources (section_id, upload_id, source_location) VALUES (%s, %s, %s)",
                                (new_section_id, source["upload_id"], source.get("location")),
                            )
                    self._snapshot_chapter_db(cursor, chapter_id, actor)
                    connection.commit()
                log_action(actor, f"Library version restored chapter_id={chapter_id} version={version_number}")
                return True
            except Exception:
                current_app.logger.exception("Library version restore failed")
                return False
        store = self._load_store()
        target = next((row for row in store["versions"] if row["chapter_id"] == chapter_id and row["version"] == version_number), None)
        if not target:
            return False
        store["sections"] = [row for row in store["sections"] if row["chapter_id"] != chapter_id]
        for section in target["snapshot"]["sections"]:
            copied = dict(section)
            copied["id"] = self._next_id(store, "section")
            copied["chapter_id"] = chapter_id
            store["sections"].append(copied)
        self._save_store(store)
        return True

    def list_sources(self, section_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT src.upload_id, u.filename, u.uploader, u.uploaded_at, src.source_location
                    FROM library_sources src
                    JOIN library_uploads u ON u.id = src.upload_id
                    WHERE src.section_id=%s
                    ORDER BY src.id
                    """,
                    (section_id,),
                )
                rows = cursor.fetchall()
            return [
                {"upload_id": row[0], "filename": row[1], "uploader": row[2], "uploaded_at": row[3], "location": row[4]}
                for row in rows
            ]
        store = self._load_store()
        matches = [row for row in store["sources"] if row["section_id"] == section_id]
        uploads = {row["id"]: row for row in store["uploads"]}
        return [
            {
                "upload_id": row["upload_id"],
                "filename": uploads[row["upload_id"]]["filename"],
                "uploader": uploads[row["upload_id"]]["uploader"],
                "uploaded_at": uploads[row["upload_id"]]["uploaded_at"],
                "location": row["source_location"],
            }
            for row in matches
        ]

    def generate_suggestions(self):
        suggestions = []
        chapters = self.list_public_chapters()
        seen = set()
        for chapter in chapters:
            key = (chapter["grade"], chapter["subject"], chapter["title"].lower())
            if key in seen:
                suggestions.append({"type": "duplicate", "text": f"Merge duplicate chapter '{chapter['title']}'"})
            seen.add(key)
        if len(chapters) < 3:
            suggestions.append({"type": "missing", "text": "Library has few published chapters; review queue may fill gaps."})
        if self._db_enabled():
            with db_connection(autocommit=False) as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM library_suggestions WHERE status='open'")
                for item in suggestions:
                    cursor.execute(
                        "INSERT INTO library_suggestions (suggestion_type, payload_json, status) VALUES (%s, %s, 'open')",
                        (item["type"], json.dumps(item)),
                    )
                connection.commit()
            return suggestions
        store = self._load_store()
        store["suggestions"] = suggestions
        self._save_store(store)
        return suggestions

    @property
    def suggestions(self):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute("SELECT payload_json FROM library_suggestions WHERE status='open' ORDER BY id DESC")
                return [json.loads(row[0]) for row in cursor.fetchall()]
        return self._load_store()["suggestions"]

    @property
    def chapters(self):
        rows = self.list_public_chapters() if self._db_enabled() else self._load_store()["chapters"]
        return [_ns(row) for row in rows]


def get_library_service():
    if "library_service" not in current_app.extensions:
        current_app.extensions["library_service"] = LibraryService()
    return current_app.extensions["library_service"]

