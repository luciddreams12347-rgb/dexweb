from dexweb import create_app
from dexweb.chat import add_message, clear_messages, room_display_name, user_can_enter_room
from dexweb.cipher import decode, encode


def make_app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "ADMIN_PASSWORD": "admin-test",
            "DB_ENABLED": False,
        }
    )
    return app


def test_cipher_round_trip_preserves_case_and_symbols():
    original = "DeX Cipher 123!"

    encoded = encode(original)
    decoded = decode(encoded)

    assert encoded == "TuC Kydruh 123!"
    assert decoded == original


def test_room_authorization_matches_grade_and_admin_rules():
    assert user_can_enter_room("general", grade=None, is_admin=False)
    assert user_can_enter_room("grade10", grade=10, is_admin=False)
    assert not user_can_enter_room("grade11", grade=10, is_admin=False)
    assert user_can_enter_room("grade11", grade=10, is_admin=True)
    assert not user_can_enter_room("unknown", grade=10, is_admin=True)


def test_room_display_names_are_template_friendly():
    assert room_display_name("general") == "General"
    assert room_display_name("grade9") == "Grade 9"


def test_index_renders_terminal_identity():
    app = make_app()

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"Welcome to" in response.data
    assert b"DeX" in response.data


def test_protected_home_redirects_to_login():
    app = make_app()

    response = app.test_client().get("/home")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_chat_ajax_escapes_message_text():
    app = make_app()
    clear_messages()
    add_message("general", "tester", 9, False, "<script>alert('x')</script>")

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "tester"
        sess["grade"] = 9
        sess["is_admin"] = False

    response = client.get("/chat/general?_ajax=1")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<script>" not in body
    assert "&lt;script&gt;alert(" in body
    assert "&lt;/script&gt;" in body
