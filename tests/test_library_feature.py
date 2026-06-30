from io import BytesIO
import threading

import pytest

from dexweb import create_app
from dexweb.features.library import service as library_service_module
from dexweb.features.library.service import get_library_service
from dexweb.features.library.worm_worker import get_worm_worker


def make_app(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "admin-test",
        "DB_ENABLED": False,
        "INSTANCE_PATH": str(tmp_path / "instance"),
        "LIBRARY_UPLOADS_DIR": str(tmp_path / "uploads"),
        "LIBRARY_MAX_UPLOAD_BYTES": 128,
    }
    config.update(overrides)
    return create_app(config)


def login_user(client, username="student", grade=10, is_admin=False):
    with client.session_transaction() as sess:
        sess["user"] = username
        sess["grade"] = grade
        sess["is_admin"] = is_admin


def upload_material(client, filename="bio.txt", payload=b"Grade 10 biology photosynthesis notes", **fields):
    data = {
        "file": (BytesIO(payload), filename),
        "grade": fields.get("grade", "10"),
        "subject": fields.get("subject", "Biology"),
        "title": fields.get("title", "Photosynthesis"),
        "description": fields.get("description", "core notes"),
    }
    return client.post("/library/upload", data=data, content_type="multipart/form-data", follow_redirects=True)


def drain_worm_queue(app, timeout=10):
    with app.app_context():
        get_worm_worker().drain(timeout=timeout)


def upload_multiple_material(client, files, **fields):
    data = {
        "files": [(BytesIO(payload), filename) for filename, payload in files],
        "grade": fields.get("grade", "10"),
        "subject": fields.get("subject", "Biology"),
        "title": fields.get("title", "Biology Notes"),
        "description": fields.get("description", "batch upload"),
    }
    return client.post("/library/upload", data=data, content_type="multipart/form-data", follow_redirects=True)


def upload_folder_material(client, files, **fields):
    data = {
        "folder_files": [(BytesIO(payload), path) for path, payload in files],
        "grade": fields.get("grade", "10"),
        "subject": fields.get("subject", "Biology"),
        "title": fields.get("title", ""),
        "description": fields.get("description", "folder upload"),
    }
    return client.post("/library/upload", data=data, content_type="multipart/form-data", follow_redirects=True)


def test_library_upload_requires_login(tmp_path):
    app = make_app(tmp_path)
    response = app.test_client().get("/library/upload")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_upload_creates_review_item_and_persists(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    response = upload_material(client)
    assert response.status_code == 200
    assert b"DEX Library" in response.data
    drain_worm_queue(app)
    with app.app_context():
        items = get_library_service().list_reviews()
        assert len(items) == 1
        assert items[0].detected_subject == "Biology"
    app2 = make_app(tmp_path)
    with app2.app_context():
        items = get_library_service().list_reviews()
        assert len(items) == 1
        assert items[0].source_file.endswith(".txt")


def test_invalid_upload_shows_error(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    response = client.post("/library/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 200
    assert b"Select a file to upload." in response.data


def test_unsupported_extension_is_rejected(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    response = upload_material(client, filename="payload.exe", payload=b"bad")
    assert response.status_code == 200
    assert b"Unsupported file type." in response.data


def test_oversized_upload_is_rejected(tmp_path):
    app = make_app(tmp_path, LIBRARY_MAX_UPLOAD_BYTES=8)
    client = app.test_client()
    login_user(client)
    response = upload_material(client, payload=b"this payload is too large")
    assert response.status_code == 200
    assert b"Uploaded file is too large." in response.data


def test_duplicate_upload_is_rejected(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    first = upload_material(client)
    second = upload_material(client)
    assert first.status_code == 200
    assert second.status_code == 200
    assert b"already uploaded" in second.data


def test_worm_ai_failure_is_handled(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)

    def boom(*args, **kwargs):
        raise RuntimeError("ai down")

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", boom)
    response = upload_material(client)
    assert response.status_code == 200
    assert b"Worm is processing" in response.data
    drain_worm_queue(app)
    with app.app_context():
        jobs = get_library_service().list_worm_jobs(statuses=["failed"])
        assert len(jobs) == 1
        assert jobs[0].error_message
        assert len(get_library_service().list_reviews()) == 0


def test_review_actions_approve_publish_unpublish_reprocess_reject(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=b"Grade 11 physics vectors and motion", subject="Physics", grade="11", title="Vectors")
    drain_worm_queue(app)
    login_user(client, username="ADMIN", grade=11, is_admin=True)

    approve = client.post(
        "/library/review",
        data={"review_id": "1", "action": "approve", "chapter_title": "Vectors", "section_title": "Intro"},
        follow_redirects=True,
    )
    assert approve.status_code == 200
    chapter = client.get("/library/chapter/1")
    assert chapter.status_code == 200
    assert b"Vectors" in chapter.data

    unpublish = client.post(
        "/library/review",
        data={"review_id": "1", "action": "unpublish", "chapter_id": "1", "chapter_title": "Vectors", "section_title": "Muted"},
        follow_redirects=True,
    )
    assert unpublish.status_code == 200
    missing = client.get("/library/chapter/1")
    assert missing.status_code == 404

    publish = client.post(
        "/library/review",
        data={"review_id": "1", "action": "publish", "chapter_id": "1", "chapter_title": "Vectors", "section_title": "Return"},
        follow_redirects=True,
    )
    assert publish.status_code == 200
    assert client.get("/library/chapter/1").status_code == 200

    reprocess = client.post("/library/review", data={"review_id": "1", "action": "reprocess"}, follow_redirects=True)
    reject = client.post("/library/review", data={"review_id": "2", "action": "reject"}, follow_redirects=True)
    assert reprocess.status_code == 200
    assert b"Reprocessed as review" in reprocess.data
    assert reject.status_code == 200
    assert b"Review item rejected." in reject.data


def test_search_filters_keyword_grade_subject_topic(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=b"Grade 10 biology photosynthesis chlorophyll sunlight", subject="Biology", grade="10", title="Photosynthesis")
    drain_worm_queue(app)
    login_user(client, username="ADMIN", grade=10, is_admin=True)
    client.post("/library/review", data={"review_id": "1", "action": "approve", "chapter_title": "Photosynthesis", "section_title": "Core"}, follow_redirects=True)

    keyword = client.get("/library/search?q=chlorophyll")
    subject = client.get("/library/search?subject=Biology")
    grade = client.get("/library/search?grade=10")
    topic = client.get("/library/search?topic=photosynthesis")
    empty = client.get("/library/search?q=algebra")

    assert b"Photosynthesis" in keyword.data
    assert b"Photosynthesis" in subject.data
    assert b"Photosynthesis" in grade.data
    assert b"Photosynthesis" in topic.data
    assert b"No results." in empty.data


def test_version_history_and_restore(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=b"Grade 10 biology first copy", title="Cells")
    drain_worm_queue(app)
    login_user(client, username="ADMIN", grade=10, is_admin=True)
    client.post("/library/review", data={"review_id": "1", "action": "approve", "chapter_title": "Cells", "section_title": "Original"}, follow_redirects=True)
    client.post("/library/review", data={"review_id": "1", "action": "publish", "chapter_id": "1", "chapter_title": "Cells", "section_title": "Updated", "content": "new copy"}, follow_redirects=True)

    with app.app_context():
        service = get_library_service()
        versions = service.list_versions(1)
        assert len(versions) >= 2
        compare = service.compare_versions(1, versions[-1]["version"], versions[0]["version"])
        assert compare is not None
        assert "Sections:" in compare["summary"]

    restore = client.post("/admin/library", data={"action": "restore_version", "chapter_id": "1", "version": "1"}, follow_redirects=True)
    assert restore.status_code == 200
    assert b"Version restored." in restore.data


def test_source_attribution_is_admin_only(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=b"Grade 10 biology source attribution sample")
    drain_worm_queue(app)
    login_user(client, username="ADMIN", grade=10, is_admin=True)
    client.post("/library/review", data={"review_id": "1", "action": "approve", "chapter_title": "Sources", "section_title": "Trace"}, follow_redirects=True)

    admin_sources = client.get("/admin/library?section_id=1")
    assert admin_sources.status_code == 200
    assert b"Source Attribution" in admin_sources.data
    assert b"student" in admin_sources.data

    login_user(client, username="student", grade=10, is_admin=False)
    public_chapter = client.get("/library/chapter/1")
    assert public_chapter.status_code == 200
    assert b"student" not in public_chapter.data


def test_admin_routes_require_admin(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client, is_admin=False)
    review = client.get("/library/review")
    admin = client.get("/admin/library")
    assert review.status_code == 302
    assert admin.status_code == 302
    assert "/admin_login" in review.headers["Location"]
    assert "/admin_login" in admin.headers["Location"]


def test_invalid_review_action_does_not_crash(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client, username="ADMIN", grade=10, is_admin=True)
    response = client.post("/library/review", data={"review_id": "abc", "action": ""}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Choose a valid review action." in response.data


def test_upload_persists_on_disk(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=b"disk persistence check")
    upload_dir = tmp_path / "uploads"
    files = list(upload_dir.iterdir())
    assert files
    assert files[0].is_file()


def test_worm_preserves_original_extracted_text(tmp_path):
    original = "Grade 10 biology\n\nPhotosynthesis   uses   chlorophyll."
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=original.encode("utf-8"))
    drain_worm_queue(app)
    with app.app_context():
        review = get_library_service().list_reviews()[0]
        assert review.extracted_text == original
        assert review.ai_suggestions
        assert "rewritten_content" not in review.ai_suggestions


def test_published_chapter_uses_original_source_text(tmp_path):
    original = "Grade 10 biology\n\nPhotosynthesis   uses   chlorophyll."
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client, payload=original.encode("utf-8"))
    drain_worm_queue(app)
    login_user(client, username="ADMIN", grade=10, is_admin=True)
    client.post(
        "/library/review",
        data={"review_id": "1", "action": "approve", "chapter_title": "Photosynthesis", "section_title": "Core"},
        follow_redirects=True,
    )
    with app.app_context():
        view = get_library_service().chapter_view(1)
    assert view["sections"][0]["content"] == original


def test_multiple_uploads_create_batch_and_reviews(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    response = upload_multiple_material(
        client,
        [
            ("cells.txt", b"Grade 10 biology cells"),
            ("photosynthesis.txt", b"Grade 10 biology photosynthesis"),
        ],
        title="Grade 10 Biology Notes",
    )
    assert response.status_code == 200
    assert b"Grade 10 Biology Notes" in response.data
    drain_worm_queue(app)
    with app.app_context():
        service = get_library_service()
        batches = service.list_batches()
        reviews = service.list_reviews()
        assert len(batches) == 1
        assert batches[0].total_files == 2
        assert batches[0].processed_files == 2
        assert len(reviews) == 2


def test_single_upload_does_not_create_batch(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client)
    drain_worm_queue(app)
    with app.app_context():
        service = get_library_service()
        assert len(service.list_batches()) == 0
        assert len(service.list_reviews()) == 1


def test_folder_upload_preserves_paths_and_batch(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    response = upload_folder_material(
        client,
        [
            ("Biology Notes/Cells.pdf", b"%PDF-1.4 cells"),
            ("Biology Notes/Photosynthesis.docx", b"PK photosynthesis"),
        ],
    )
    assert response.status_code == 200
    drain_worm_queue(app)
    with app.app_context():
        service = get_library_service()
        batches = service.list_batches()
        assert len(batches) == 1
        assert batches[0].source_type == "folder"
        batch = service.get_batch(batches[0].id)
        paths = {item["folder_path"] for item in batch.uploads}
        assert "Biology Notes" in paths


def test_upload_returns_before_worm_completes(tmp_path, monkeypatch):
    gate = threading.Event()
    original = library_service_module.run_worm_pipeline_timed

    def blocked(*args, **kwargs):
        gate.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", blocked)
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    response = upload_material(client)
    assert response.status_code == 200
    assert b"Worm is processing" in response.data
    with app.app_context():
        service = get_library_service()
        assert len(service.list_reviews()) == 0
        jobs = service.list_worm_jobs(statuses=["pending", "processing"])
        assert len(jobs) == 1
    gate.set()
    drain_worm_queue(app)
    with app.app_context():
        assert len(get_library_service().list_reviews()) == 1


def test_worm_retry_after_failure(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)

    calls = {"count": 0}
    original = library_service_module.run_worm_pipeline_timed

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("ai down")
        return original(*args, **kwargs)

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", flaky)
    upload_material(client)
    drain_worm_queue(app)
    with app.app_context():
        service = get_library_service()
        failed = service.list_worm_jobs(statuses=["failed"])
        assert len(failed) == 1
        assert len(service.list_reviews()) == 0
    login_user(client, username="ADMIN", grade=10, is_admin=True)
    retry = client.post(
        "/library/review",
        data={"upload_id": "1", "action": "retry_worm"},
        follow_redirects=True,
    )
    assert retry.status_code == 200
    drain_worm_queue(app)
    with app.app_context():
        service = get_library_service()
        assert len(service.list_reviews()) == 1
        completed = service.list_worm_jobs(statuses=["completed"])
        assert len(completed) >= 1

