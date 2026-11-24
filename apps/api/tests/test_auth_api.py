from sqlalchemy import select, update

from app.models import User
from tests.conftest import register


def test_register_sets_cookie_and_returns_user(client) -> None:
    body = register(client, email="Priya@Example.com")
    assert body["email"] == "priya@example.com"
    assert "password_hash" not in body
    assert "pare_session" in client.cookies
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "priya@example.com"


def test_password_is_hashed_in_database(client, db_session) -> None:
    register(client)
    user = db_session.scalar(select(User))
    assert user.password_hash.startswith("$2")
    assert "correct-horse-42" not in user.password_hash


def test_duplicate_email_is_case_insensitive(client, make_client) -> None:
    register(client, email="a@example.com")
    r = make_client().post(
        "/api/v1/auth/register",
        json={"email": "A@EXAMPLE.com", "password": "another-pass-1", "display_name": "A"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


def test_register_validation(client) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short", "display_name": " "},
    )
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    fields = {tuple(f["loc"])[-1] for f in body["details"]["fields"]}
    assert {"email", "password", "display_name"} <= fields


def test_register_rejects_letters_only_password(client) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": "abcdefghijkl", "display_name": "X"},
    )
    assert r.status_code == 422


def test_login_success_and_bearer_token(make_client) -> None:
    c = make_client()
    register(c)
    fresh = make_client()
    r = fresh.post(
        "/api/v1/auth/login", json={"email": "priya@example.com", "password": "correct-horse-42"}
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    # Bearer auth works without cookies or CSRF header.
    bare = make_client(csrf=False)
    me = bare.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_login_wrong_password_is_generic(make_client) -> None:
    register(make_client())
    c = make_client()
    wrong_pw = c.post("/api/v1/auth/login", json={"email": "priya@example.com", "password": "nope"})
    no_user = c.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]


def test_login_rate_limited(make_client) -> None:
    c = make_client()
    codes = [
        c.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "bad"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_me_requires_auth(client) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_tampered_token_rejected(make_client) -> None:
    c = make_client(csrf=False)
    r = c.get("/api/v1/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


def test_logout_clears_cookie(auth_client) -> None:
    assert auth_client.post("/api/v1/auth/logout").status_code == 204
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_token_version_bump_revokes_sessions(auth_client, db_session) -> None:
    db_session.execute(update(User).values(token_version=User.token_version + 1))
    db_session.commit()
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_inactive_user_rejected(auth_client, db_session) -> None:
    db_session.execute(update(User).values(is_active=False))
    db_session.commit()
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_csrf_header_required_for_cookie_requests(auth_client, make_client) -> None:
    # Same cookie jar but without the CSRF header.
    r = auth_client.post("/api/v1/projects", json={"name": "X"}, headers={"X-PARE-CSRF": ""})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_REQUIRED"


def test_foreign_origin_rejected(auth_client) -> None:
    r = auth_client.post(
        "/api/v1/projects", json={"name": "X"}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_ORIGIN"


def test_allowed_origin_gets_cors_headers(auth_client) -> None:
    r = auth_client.post(
        "/api/v1/projects", json={"name": "X"}, headers={"Origin": "http://localhost:3000"}
    )
    assert r.status_code == 201
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_untrusted_host_rejected(make_client) -> None:
    r = make_client().get("/health", headers={"Host": "attacker.example"})
    assert r.status_code == 400


def test_registration_can_be_disabled(make_client, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ALLOW_REGISTRATION", "false")
    get_settings.cache_clear()
    try:
        from fastapi.testclient import TestClient

        c = TestClient(create_app(), headers={"X-PARE-CSRF": "1"})
        r = c.post(
            "/api/v1/auth/register",
            json={"email": "z@example.com", "password": "correct-horse-42", "display_name": "Z"},
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "REGISTRATION_DISABLED"
    finally:
        monkeypatch.setenv("ALLOW_REGISTRATION", "true")
        get_settings.cache_clear()
