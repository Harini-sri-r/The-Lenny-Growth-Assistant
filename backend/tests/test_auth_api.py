"""Account registration and cookie-authentication security tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import get_db
from app.main import app
from app.models import Base
from app.models.chat import AuthSession, ChatArtifact, ChatSession, ChatUser


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def csrf(client):
    client.headers["X-CSRF-Token"] = client.cookies.get("lenny_csrf", "")


def register(client, credentials):
    return client.post("/api/v1/auth/register", json=credentials)


def sign_in(client, credentials):
    response = client.post("/api/v1/auth/login", json=credentials)
    assert response.status_code == 200
    csrf(client)
    return response


def test_register_creates_account_without_authenticating(client):
    response = register(client, {
        "email": " PERSON@example.test ", "password": "a long and private password",
        "display_name": "Person",
    })
    assert response.status_code == 201
    assert response.json()["email"] == "person@example.test"
    assert "password" not in response.json() and "password_hash" not in response.json()
    assert "set-cookie" not in response.headers
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/chat/sessions").status_code == 401

    login_response = client.post("/api/v1/auth/login", json={
        "email": "person@example.test", "password": "a long and private password",
    })
    assert login_response.status_code == 200
    assert "httponly" in login_response.headers.get("set-cookie", "").lower()
    assert login_response.headers.get("x-csrf-token") == client.cookies.get("lenny_csrf")
    user_id = response.json()["id"]
    csrf(client)
    session = client.post("/api/v1/chat/sessions", json={}).json()
    assert session["user_id"] == user_id


def test_invalid_login_duplicate_registration_and_logout_revoke_session(client):
    payload = {"email": "person@example.test", "password": "a long and private password"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert "Try signing in" in duplicate.json()["detail"]
    wrong_password = client.post("/api/v1/auth/login", json={"email": payload["email"], "password": "wrong"})
    assert wrong_password.status_code == 401
    assert wrong_password.json()["detail"] == "Email or password is incorrect"
    missing_account = client.post("/api/v1/auth/login", json={"email": "missing@example.test", "password": "wrong"})
    assert missing_account.status_code == 401
    assert missing_account.json()["detail"] == wrong_password.json()["detail"]
    assert client.post("/api/v1/auth/login", json=payload).status_code == 200
    csrf(client)
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_clears_expired_or_missing_session_cookies(client):
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert 'lenny_session=""' in response.headers.get("set-cookie", "")


def test_logout_requires_csrf_for_a_valid_session(client):
    credentials = {"email": "logout@example.test", "password": "a long and private password"}
    assert register(client, credentials).status_code == 201
    sign_in(client, credentials)
    client.headers.pop("X-CSRF-Token", None)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    csrf(client)
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_missing_and_expired_auth_sessions_have_distinct_safe_responses(client):
    anonymous = client.get("/api/v1/auth/me")
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"] == "Sign in to continue"
    credentials = {"email": "expired@example.test", "password": "a long and private password"}
    assert register(client, credentials).status_code == 201
    sign_in(client, credentials)
    token = client.cookies.get("lenny_session")
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    from app.models.chat import AuthSession
    from datetime import datetime, timedelta, timezone
    import hashlib
    db_session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    db_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()
    next(db_generator, None)
    expired = client.get("/api/v1/auth/me")
    assert expired.status_code == 401
    assert expired.json()["detail"] == "Your session expired. Sign in again"
    client.headers.pop("X-CSRF-Token", None)
    cleared = client.post("/api/v1/auth/logout")
    assert cleared.status_code == 204
    assert 'lenny_session=""' in cleared.headers.get("set-cookie", "")


def test_https_authentication_marks_both_cookies_secure(client):
    client.base_url = "https://testserver"
    credentials = {"email": "secure@example.test", "password": "a long and private password"}
    assert register(client, credentials).status_code == 201
    response = client.post("/api/v1/auth/login", json=credentials)
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert all("secure" in cookie.lower() for cookie in cookies)


def test_login_rotates_and_revokes_existing_browser_session(client):
    credentials = {"email": "rotate@example.test", "password": "a long and private password"}
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    old_token = client.cookies.get("lenny_session")
    login_response = client.post("/api/v1/auth/login", json=credentials)
    new_token = client.cookies.get("lenny_session")
    assert login_response.status_code == 200
    assert new_token and new_token != old_token
    client.cookies.set("lenny_session", old_token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_csrf_is_required_for_authenticated_mutations(client):
    credentials = {"email": "person@example.test", "password": "a long and private password"}
    assert register(client, credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    response = client.post("/api/v1/chat/sessions", json={})
    assert response.status_code == 403


def test_csrf_rejects_a_present_but_invalid_token(client):
    credentials = {"email": "person@example.test", "password": "a long and private password"}
    assert register(client, credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    response = client.post(
        "/api/v1/chat/sessions", json={},
        headers={"X-CSRF-Token": "not-the-cookie-token"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Request verification failed. Refresh and try again"


def test_auth_rejects_unconfigured_origins_and_blank_registration_password(client):
    bad_origin = client.post("/api/v1/auth/register", headers={"Origin": "https://attacker.example"}, json={
        "email": "person@example.test", "password": "a long and private password",
    })
    assert bad_origin.status_code == 403
    blank_password = client.post("/api/v1/auth/register", json={
        "email": "person@example.test", "password": "            ",
    })
    assert blank_password.status_code == 422


def test_user_owned_routes_require_authentication(client):
    assert client.get("/api/v1/chat/sessions").status_code == 401
    assert client.get("/api/v1/artifacts").status_code == 401
    assert client.post("/api/v1/chat/sessions", json={}).status_code == 401


def test_users_cannot_access_or_delete_another_users_session(client):
    first = {"email": "first@example.test", "password": "a long and private password"}
    second = {"email": "second@example.test", "password": "another private password"}
    client.post("/api/v1/auth/register", json=first)
    sign_in(client, first)
    csrf(client)
    first_session = client.post("/api/v1/chat/sessions", json={}).json()
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    db.add(ChatArtifact(
        user_id=first_session["user_id"], session_id=first_session["id"],
        title="Private artifact", artifact_format="markdown", content="# Private",
        sources=[], word_count=1,
    ))
    db.commit()
    db.close()
    next(db_generator, None)
    client.post("/api/v1/auth/register", json=second)
    sign_in(client, second)
    assert client.get(f"/api/v1/chat/sessions/{first_session['id']}/messages").status_code == 404
    assert client.delete(f"/api/v1/chat/sessions/{first_session['id']}").status_code == 404
    assert client.get("/api/v1/artifacts").json() == []


def test_profile_can_be_updated_and_returns_real_creation_date(client):
    created = client.post("/api/v1/auth/register", json={
        "email": "profile@example.test", "password": "a long and private password", "display_name": "Original",
    }).json()
    assert created["created_at"]
    assert created["appearance_mode"] == "light" and created["pastel_palette"] == "pink"
    sign_in(client, {"email": "profile@example.test", "password": "a long and private password"})
    csrf(client)
    updated = client.patch("/api/v1/auth/me", json={"display_name": "  Updated Name  "})
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated Name"
    assert updated.json()["id"] == created["id"]
    assert client.patch("/api/v1/auth/me", json={"display_name": "   "}).status_code == 422
    preferences = client.patch("/api/v1/auth/preferences", json={"appearance_mode": "dark", "pastel_palette": "lavender"})
    assert preferences.status_code == 200
    assert preferences.json()["appearance_mode"] == "dark"
    assert preferences.json()["pastel_palette"] == "lavender"
    assert client.patch("/api/v1/auth/preferences", json={"appearance_mode": "blue", "pastel_palette": "neon"}).status_code == 422


def test_delete_account_requires_confirmation_password_and_removes_only_owned_records(client):
    first_credentials = {"email": "remove@example.test", "password": "a long and private password"}
    first = client.post("/api/v1/auth/register", json=first_credentials).json()
    sign_in(client, first_credentials)
    csrf(client)
    first_chat = client.post("/api/v1/chat/sessions", json={}).json()
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    db.add(ChatArtifact(user_id=first["id"], session_id=first_chat["id"], title="Owned", artifact_format="markdown", content="# owned", sources=[], word_count=1))
    db.commit(); db.close(); next(db_generator, None)

    second_credentials = {"email": "keep@example.test", "password": "another private password"}
    second = client.post("/api/v1/auth/register", json=second_credentials).json()
    sign_in(client, second_credentials)
    second_chat = client.post("/api/v1/chat/sessions", json={}).json()
    wrong = client.request("DELETE", "/api/v1/auth/account", json={"confirmation": "DELETE", "password": "wrong password"})
    assert wrong.status_code == 400
    assert client.get("/api/v1/auth/me").status_code == 200

    deleted = client.request("DELETE", "/api/v1/auth/account", json={"confirmation": "DELETE", "password": second_credentials["password"]})
    assert deleted.status_code == 204
    assert 'lenny_session=""' in deleted.headers.get("set-cookie", "")
    assert client.get("/api/v1/auth/me").status_code == 401

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    assert db.get(ChatUser, second["id"]) is None
    assert db.get(ChatUser, first["id"]) is not None
    assert db.get(ChatSession, first_chat["id"]) is not None
    assert db.get(ChatSession, second_chat["id"]) is None
    assert db.query(ChatArtifact).filter_by(user_id=first["id"]).count() == 1
    assert db.query(AuthSession).filter_by(user_id=second["id"]).count() == 0
    db.close(); next(db_generator, None)
    assert client.post("/api/v1/auth/login", json=second_credentials).status_code == 401
    assert client.post("/api/v1/auth/login", json=first_credentials).status_code == 200
