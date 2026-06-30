import json
from pathlib import Path
from types import SimpleNamespace

from flask import current_app

from ...database import db_connection, db_cursor, log_action
from ..dex.service import get_dex_service
from .uploads import load_upload_text
from .worm import run_worm_pipeline


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
            "next_ids": {"upload": 1, "review": 1, "book": 1, "chapter": 1, "section": 1, "version": 1, "suggestion": 1},
            "uploads": [],
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
        if not path.exists():
            return self._empty_store()
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_store(self, store):
        path = self._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    def _next_id(self, store, key):
        value = store["next_ids"][key]
        store["next_ids"][key] += 1
        return value

    def _load_upload(self, upload_id):
        if self._db_enabled():
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.id, u.uploader, u.filename, u.stored_path, g.grade_level, s.name, u.title, u.description,
                           u.uploaded_at, u.status, u.original_filename, u.mime_type, u.file_size, u.sha256
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

    def create_upload(self, uploader, filename, stored_path, grade, subject, title, description, original_filename=None, mime_type="", file_size=0, sha256=""):
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
                        (uploader, filename, stored_path, title, description, grade_id, subject_id, status,
                         original_filename, mime_type, file_size, sha256)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                        """,
                        (
                            uploader,
                            filename,
                            stored_path,
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
            "uploader": uploader,
            "filename": filename,
            "stored_path": stored_path,
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

    def run_worm(self, upload_id):
        upload = self._load_upload(upload_id)
        if not upload:
            raise ValueError("Upload not found.")
        try:
            extracted_text = load_upload_text(upload.stored_path)
            processed = run_worm_pipeline(get_dex_service(), upload, extracted_text)
        except OSError as error:
            log_action(upload.uploader, f"Library worm processing failure upload_id={upload_id}")
            raise ValueError(f"Could not read uploaded file: {error}") from error
        except Exception as error:
            current_app.logger.exception("Library worm processing failed")
            log_action(upload.uploader, f"Library worm processing failure upload_id={upload_id}")
            raise ValueError("Worm could not process this upload right now.") from error

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
                cursor.execute("UPDATE library_uploads SET status='processed' WHERE id=%s", (upload_id,))
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
                "source_file": upload.filename,
                "status": "pending",
                "created_at": "now",
            }
        )
        for item in store["uploads"]:
            if item["id"] == upload_id:
                item["status"] = "processed"
        self._save_store(store)
        return self.get_review(review_id)

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
                refreshed = self.run_worm(item.upload_id)
            else:
                store = self._load_store()
                for review in store["reviews"]:
                    if review["id"] == review_id:
                        review["status"] = "reprocessed"
                self._save_store(store)
                refreshed = self.run_worm(item.upload_id)
            return {"ok": True, "message": f"Reprocessed as review #{refreshed.id}."}

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

