import pytest

from dexweb import create_app
from dexweb.features.library.service import WormJobPermissionError, get_library_service


def test_create_app_survives_worm_init_failure(tmp_path, monkeypatch):
    def boom(self, app):
        raise RuntimeError("worm init failed")

    monkeypatch.setattr("dexweb.features.library.worm_worker.WormWorker.init_app", boom)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DB_ENABLED": False,
            "INSTANCE_PATH": str(tmp_path / "instance"),
        }
    )
    assert app is not None
    client = app.test_client()
    response = client.get("/")
    assert response.status_code in {200, 302}


def test_wsgi_app_is_importable(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT", "8765")
    import importlib

    import wsgi

    importlib.reload(wsgi)
    assert wsgi.app is not None
    assert wsgi.application is wsgi.app


def test_recover_skips_cancelled_jobs(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DB_ENABLED": False,
            "INSTANCE_PATH": str(tmp_path / "instance"),
            "LIBRARY_UPLOADS_DIR": str(tmp_path / "uploads"),
        }
    )
    enqueued = []

    def capture(upload_id, job_id):
        enqueued.append((upload_id, job_id))

    with app.app_context():
        service = get_library_service()
        store = service._load_store()
        store["uploads"].append(
            {
                "id": 1,
                "uploader": "student",
                "filename": "a.txt",
                "stored_path": "x",
                "status": "cancelled",
                "batch_id": None,
                "original_filename": "a.txt",
            }
        )
        store["worm_jobs"].append(
            {
                "id": 1,
                "upload_id": 1,
                "status": "processing",
                "started_at": None,
                "completed_at": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "error_message": None,
                "created_at": "now",
            }
        )
        service._save_store(store)
        service.recover_worm_jobs(capture)
        job = service.get_worm_job(1)
        assert job.status == "cancelled"
        assert enqueued == []


def test_stale_processing_job_is_requeued(tmp_path):
    from datetime import datetime, timedelta, timezone

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DB_ENABLED": False,
            "INSTANCE_PATH": str(tmp_path / "instance"),
            "LIBRARY_UPLOADS_DIR": str(tmp_path / "uploads"),
            "WORM_STALE_PROCESSING_SECONDS": 60,
        }
    )
    enqueued = []
    stale_started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    with app.app_context():
        service = get_library_service()
        store = service._load_store()
        store["uploads"].append(
            {
                "id": 1,
                "uploader": "student",
                "filename": "a.txt",
                "stored_path": "x",
                "status": "processing",
                "batch_id": None,
                "original_filename": "a.txt",
            }
        )
        store["worm_jobs"].append(
            {
                "id": 1,
                "upload_id": 1,
                "status": "processing",
                "started_at": stale_started,
                "completed_at": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "error_message": None,
                "created_at": stale_started,
            }
        )
        service._save_store(store)
        service.recover_worm_jobs(lambda upload_id, job_id: enqueued.append((upload_id, job_id)))
        job = service.get_worm_job(1)
        assert job.status == "pending"
        assert enqueued == [(1, 1)]


def test_user_cannot_view_other_users_worm_job(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DB_ENABLED": False,
            "INSTANCE_PATH": str(tmp_path / "instance"),
        }
    )
    with app.app_context():
        service = get_library_service()
        store = service._load_store()
        store["uploads"].append(
            {
                "id": 1,
                "uploader": "alice",
                "filename": "a.txt",
                "stored_path": "x",
                "status": "pending",
                "original_filename": "a.txt",
            }
        )
        store["worm_jobs"].append(
            {
                "id": 1,
                "upload_id": 1,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "error_message": None,
                "created_at": "now",
            }
        )
        service._save_store(store)
        with pytest.raises(WormJobPermissionError):
            service.get_worm_job_for_actor(1, actor="bob", is_admin=False)


def test_uploader_can_view_own_worm_job(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DB_ENABLED": False,
            "INSTANCE_PATH": str(tmp_path / "instance"),
        }
    )
    with app.app_context():
        service = get_library_service()
        store = service._load_store()
        store["uploads"].append(
            {
                "id": 1,
                "uploader": "alice",
                "filename": "a.txt",
                "stored_path": "x",
                "status": "pending",
                "original_filename": "a.txt",
            }
        )
        store["worm_jobs"].append(
            {
                "id": 1,
                "upload_id": 1,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "error_message": None,
                "created_at": "now",
            }
        )
        service._save_store(store)
        job = service.get_worm_job_for_actor(1, actor="alice", is_admin=False)
        assert job.id == 1
