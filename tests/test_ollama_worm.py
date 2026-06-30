from io import BytesIO
import threading
from unittest.mock import MagicMock, patch

import pytest

from dexweb import create_app
from dexweb.features.dex.ollama_client import (
    OllamaCancelledError,
    OllamaConnectionError,
    OllamaTimeoutError,
    generate_chat,
    probe_connection,
)
from dexweb.features.library import service as library_service_module
from dexweb.features.library.service import WormJobPermissionError, get_library_service
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
        "OLLAMA_CONNECT_TIMEOUT": 2,
        "OLLAMA_GENERATION_TIMEOUT": None,
        "OLLAMA_MAX_RETRIES": 1,
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


def test_ollama_unavailable_raises_connection_error():
    with patch("dexweb.features.dex.ollama_client._chat_with_http_client", side_effect=OllamaConnectionError("offline")):
        with pytest.raises(OllamaConnectionError):
            generate_chat("http://localhost:11434", "qwen2.5:7b", [{"role": "user", "content": "hi"}], max_retries=0)


def test_ollama_generation_timeout_when_enabled():
    with patch(
        "dexweb.features.dex.ollama_client._chat_with_http_client",
        side_effect=OllamaTimeoutError("Ollama generation exceeded 5s timeout."),
    ):
        with pytest.raises(OllamaTimeoutError):
            generate_chat(
                "http://localhost:11434",
                "qwen2.5:7b",
                [{"role": "user", "content": "hi"}],
                generation_timeout=5,
                max_retries=0,
            )


def test_ollama_generation_without_timeout_allows_long_calls():
    with patch("dexweb.features.dex.ollama_client._chat_with_http_client", return_value="slow answer") as mocked:
        content = generate_chat(
            "http://localhost:11434",
            "qwen2.5:7b",
            [{"role": "user", "content": "hi"}],
            generation_timeout=None,
            max_retries=0,
        )
    assert content == "slow answer"
    assert mocked.call_args.args[6] is None


def test_ollama_cloudflare_failure_is_retryable(tmp_path):
    app = make_app(tmp_path, DEX_PROVIDER="ollama", OLLAMA_MAX_RETRIES=1)
    attempts = {"count": 0}

    def flaky(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OllamaConnectionError("Could not reach Ollama: connection refused")
        return "recovered"

    with patch("dexweb.features.dex.ollama_client._chat_with_http_client", side_effect=flaky):
        with app.app_context():
            from dexweb.features.dex.service import get_dex_service

            result = get_dex_service().process(prompt="hello", context={"feature": "test"})
    assert result["ok"] is True
    assert result["content"] == "recovered"
    assert attempts["count"] == 2


def test_ollama_cancel_check_aborts_request():
    with pytest.raises(OllamaCancelledError):
        generate_chat(
            "http://localhost:11434",
            "qwen2.5:7b",
            [{"role": "user", "content": "hi"}],
            cancel_check=lambda: True,
            max_retries=0,
        )


def test_probe_connection_reports_dns_failure():
    with patch("dexweb.features.dex.ollama_client.urlopen", side_effect=OSError("name or service not known")):
        with pytest.raises(OllamaConnectionError):
            probe_connection("http://tunnel.example.com:11434", connect_timeout=1)


def test_worm_jobs_require_admin(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        service = get_library_service()
        with pytest.raises(WormJobPermissionError):
            service.list_worm_jobs(is_admin=False)


def test_admin_can_view_worm_jobs_page(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client, username="ADMIN", is_admin=True)
    response = client.get("/admin/library/worm")
    assert response.status_code == 200
    assert b"Worm Jobs" in response.data


def test_non_admin_cannot_view_worm_jobs_page(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client, is_admin=False)
    response = client.get("/admin/library/worm")
    assert response.status_code == 302
    assert "/admin_login" in response.headers["Location"]


def test_user_can_cancel_own_pending_upload(tmp_path, monkeypatch):
    gate = threading.Event()
    original = library_service_module.run_worm_pipeline_timed

    def blocked(*args, **kwargs):
        gate.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", blocked)
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client)
    with app.app_context():
        job = get_library_service()._list_worm_jobs_internal(statuses=["pending", "processing"], limit=1)[0]
    cancel = client.post(f"/library/upload/{job.upload_id}/cancel", follow_redirects=True)
    assert cancel.status_code == 200
    with app.app_context():
        upload = get_library_service()._load_upload(job.upload_id)
        assert upload.status == "cancelled"
        assert get_library_service().get_worm_job(job.id).status == "cancelled"
    gate.set()
    drain_worm_queue(app)
    with app.app_context():
        job = get_library_service().get_worm_job(job.id)
        assert job.status == "cancelled"
        assert len(get_library_service().list_reviews()) == 0


def test_admin_can_cancel_worm_job(tmp_path, monkeypatch):
    gate = threading.Event()
    original = library_service_module.run_worm_pipeline_timed

    def blocked(*args, **kwargs):
        gate.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", blocked)
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)
    upload_material(client)
    login_user(client, username="ADMIN", is_admin=True)
    with app.app_context():
        job = get_library_service()._list_worm_jobs_internal(statuses=["pending", "processing"], limit=1)[0]
    response = client.post(
        "/admin/library/worm",
        data={"action": "cancel_worm", "job_id": str(job.id)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    gate.set()
    drain_worm_queue(app)
    with app.app_context():
        refreshed = get_library_service().get_worm_job(job.id)
        assert refreshed.status == "cancelled"


def test_slow_generation_without_timeout_completes(tmp_path, monkeypatch):
    gate = threading.Event()
    original = library_service_module.run_worm_pipeline_timed

    def slow(*args, **kwargs):
        gate.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", slow)
    app = make_app(tmp_path, OLLAMA_GENERATION_TIMEOUT=None)
    client = app.test_client()
    login_user(client)
    response = upload_material(client)
    assert b"Processing continues" in response.data
    gate.set()
    drain_worm_queue(app, timeout=15)
    with app.app_context():
        assert len(get_library_service().list_reviews()) == 1


def test_generation_timeout_enabled_marks_job_failed(tmp_path, monkeypatch):
    def slow(*args, **kwargs):
        import time

        time.sleep(0.2)
        return original(*args, **kwargs)

    original = library_service_module.run_worm_pipeline_timed

    monkeypatch.setattr(library_service_module, "run_worm_pipeline_timed", slow)
    app = make_app(tmp_path, OLLAMA_GENERATION_TIMEOUT=0)
    client = app.test_client()
    login_user(client)
    upload_material(client)
    drain_worm_queue(app, timeout=15)
    with app.app_context():
        jobs = get_library_service().list_worm_jobs(statuses=["failed"], is_admin=True)
        assert len(jobs) == 1
