from dexweb import create_app


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


def login_user(client, username="tester"):
    with client.session_transaction() as sess:
        sess["user"] = username
        sess["grade"] = 10
        sess["is_admin"] = False


def test_dex_page_requires_login(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    response = client.get("/dex")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dex_page_renders_for_logged_in_user(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)

    response = client.get("/dex")

    assert response.status_code == 200
    assert b"Start a conversation with DEX." in response.data
    assert b"Message DEX..." in response.data


def test_dex_chat_sends_message_and_keeps_history(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)

    first = client.post("/dex", data={"prompt": "Hello DEX", "action": "send"}, follow_redirects=True)
    second = client.post("/dex", data={"prompt": "Follow up", "action": "send"}, follow_redirects=True)

    assert first.status_code == 200
    assert b"Hello DEX" in first.data
    assert b"structured response" in first.data
    assert second.status_code == 200
    assert b"Follow up" in second.data
    assert first.data.count(b"structured response") == 1
    assert second.data.count(b"structured response") == 2

    with client.session_transaction() as sess:
        messages = sess["dex_messages"]

    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello DEX"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "Follow up"


def test_dex_clear_resets_conversation(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)

    client.post("/dex", data={"prompt": "Hello DEX", "action": "send"}, follow_redirects=True)
    response = client.post("/dex", data={"action": "clear"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Start a conversation with DEX." in response.data

    with client.session_transaction() as sess:
        assert "dex_messages" not in sess


def test_home_navigation_includes_dex_link(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    login_user(client)

    response = client.get("/home")

    assert response.status_code == 200
    assert b">DEX</a>" in response.data
    assert b'href="/dex"' in response.data
