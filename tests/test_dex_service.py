from dexweb import create_app
from dexweb.features.dex.service import get_dex_service


def make_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "ADMIN_PASSWORD": "admin-test",
            "DB_ENABLED": False,
            "DEX_SYSTEM_PROMPT_PATH": str(tmp_path / "dex-system-prompt.txt"),
        }
    )


def login_admin(client):
    with client.session_transaction() as sess:
        sess["user"] = "ADMIN"
        sess["is_admin"] = True


def test_dex_loads_default_system_prompt(tmp_path):
    app = make_app(tmp_path)

    with app.app_context():
        prompt = get_dex_service().get_system_prompt()

    assert "You are DEX, the central intelligence system of DexWeb." in prompt
    assert "Do not fabricate information." in prompt


def test_dex_process_returns_structured_response(tmp_path):
    app = make_app(tmp_path)

    with app.app_context():
        response = get_dex_service().process("Summarize this")

    assert response["ok"] is True
    assert response["service"] == "DEX"
    assert response["provider"] == "local-placeholder"
    assert response["request"]["prompt"] == "Summarize this"
    assert "structured response" in response["content"]


def test_admin_page_shows_dex_controls_only_for_admin(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    anonymous_response = client.get("/admin")
    assert anonymous_response.status_code == 302
    assert "/admin_login" in anonymous_response.headers["Location"]

    login_admin(client)
    admin_response = client.get("/admin")

    assert admin_response.status_code == 200
    assert b"DEX Controls" in admin_response.data
    assert b"dex_system_prompt" in admin_response.data


def test_admin_can_save_and_export_dex_prompt(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    response = client.post(
        "/admin",
        data={"action": "dex_save_prompt", "dex_system_prompt": "Custom DEX prompt"},
        follow_redirects=True,
    )
    export_response = client.get("/admin/dex/system-prompt.txt")

    assert response.status_code == 200
    assert b"DEX system prompt saved." in response.data
    assert export_response.status_code == 200
    assert export_response.get_data(as_text=True) == "Custom DEX prompt"


def test_admin_can_reset_dex_runtime_state_without_restarting(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_admin(client)

    with app.app_context():
        service = get_dex_service()
        service.runtime_state["temporary"] = "value"

    response = client.post("/admin", data={"action": "dex_reset"}, follow_redirects=True)

    with app.app_context():
        runtime_state = get_dex_service().runtime_state

    assert response.status_code == 200
    assert b"DEX reset complete." in response.data
    assert runtime_state == {}
