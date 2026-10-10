import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import get_db
from app.main import app
from app.models import Base
from app.services.container import get_rag_service
from app.services.container import get_claude_research_agent
from app.services.rag import Answer, SourceReference


class StubRAG:
    def __init__(self, failure=None):
        self.failure = failure

    def answer(self, question):
        if self.failure:
            raise self.failure
        return Answer(
            answer=f"Evidence-based answer to: {question} [S1]",
            grounded=True,
            sources=[SourceReference("S1", "Sample episode", "podcast", "podcasts/sample.md", "https://example.test/episode", "chunk-1")],
        )


class StubEssayAgent:
    def __init__(self, answer=None):
        self.result = answer or Answer(
            answer="# A useful grounded essay\n\nProduct teams should test their assumptions with customers. [S1]",
            grounded=True,
            sources=[SourceReference("S1", "Sample episode", "podcast", "podcasts/sample.md", "https://example.test/episode", "chunk-1")],
        )

    def answer(self, prompt, *, system_prompt=None):
        return self.result


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
    app.dependency_overrides[get_rag_service] = lambda: StubRAG()
    app.dependency_overrides[get_claude_research_agent] = lambda: StubEssayAgent()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_session(client, user_id):
    response = client.post("/api/v1/chat/sessions", json={"user_id": user_id, "display_name": "Workspace"})
    assert response.status_code == 201
    return response.json()


def test_sessions_are_independent_and_messages_persist(client):
    first = create_session(client, "user-one-123")
    second = create_session(client, "user-one-123")
    other_user = create_session(client, "user-two-456")
    assert first["id"] != second["id"]
    assert first["created_at"] and first["updated_at"]

    listed = client.get("/api/v1/chat/sessions", params={"user_id": "user-one-123"})
    assert listed.status_code == 200
    assert any(item["id"] == first["id"] and item["user_id"] == "user-one-123" for item in listed.json())

    response = client.post(f"/api/v1/chat/sessions/{first['id']}/messages", json={"user_id": "user-one-123", "message": "How should teams prioritize?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_message"]["sources"][0]["source_id"] == "S1"
    assert payload["assistant_message"]["sources"][0]["url"] == "https://example.test/episode"
    assert payload["assistant_message"]["grounded"] is True

    history = client.get(f"/api/v1/chat/sessions/{first['id']}/messages", params={"user_id": "user-one-123"})
    assert [message["role"] for message in history.json()] == ["user", "assistant"]
    assert all(message["session_id"] == first["id"] and message["created_at"] for message in history.json())
    assert history.json()[0]["content"] == "How should teams prioritize?"
    assert history.json()[1]["content"] == payload["assistant_message"]["content"]
    assert history.json()[1]["sources"][0]["chunk_id"] == "chunk-1"
    assert client.get(f"/api/v1/chat/sessions/{second['id']}/messages", params={"user_id": "user-one-123"}).json() == []
    assert client.get(f"/api/v1/chat/sessions/{first['id']}/messages", params={"user_id": "user-two-456"}).status_code == 404
    assert other_user["user_id"] != first["user_id"]


def test_send_message_rejects_nonexistent_or_other_users_session(client):
    missing_id = "00000000-0000-0000-0000-000000000000"
    missing = client.post(
        f"/api/v1/chat/sessions/{missing_id}/messages",
        json={"user_id": "user-one-123", "message": "Question"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Chat session not found"

    owned_by_other = create_session(client, "user-two-456")
    forbidden = client.post(
        f"/api/v1/chat/sessions/{owned_by_other['id']}/messages",
        json={"user_id": "user-one-123", "message": "Question"},
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["detail"] == "Chat session not found"


def test_provider_failure_returns_safe_503_and_keeps_user_message(client):
    app.dependency_overrides[get_rag_service] = lambda: StubRAG(RuntimeError("private machine details"))
    session = create_session(client, "user-one-123")
    response = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"user_id": "user-one-123", "message": "Question"})
    assert response.status_code == 503
    assert "private machine details" not in response.text
    history = client.get(f"/api/v1/chat/sessions/{session['id']}/messages", params={"user_id": "user-one-123"})
    assert [message["role"] for message in history.json()] == ["user"]


def test_blank_message_is_rejected(client):
    session = create_session(client, "user-one-123")
    response = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"user_id": "user-one-123", "message": "   "})
    assert response.status_code == 422


def test_insufficient_evidence_is_persisted_without_citations(client):
    app.dependency_overrides[get_rag_service] = lambda: type("EmptyRAG", (), {"answer": lambda _self, _question: Answer("I couldn't find relevant evidence.", [], False)})()
    session = create_session(client, "user-one-123")
    response = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"user_id": "user-one-123", "message": "Question"})
    assert response.status_code == 200
    assistant = response.json()["assistant_message"]
    assert assistant["grounded"] is False
    assert assistant["sources"] == []


def test_ship30_artifact_persists_grounded_sources(client):
    session = create_session(client, "user-one-123")
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": "Customer research",
        "audience": "early-stage founders", "artifact_format": "markdown",
    })
    assert response.status_code == 201
    artifact = response.json()
    assert artifact["title"] == "A useful grounded essay"
    assert artifact["word_count"] > 0
    assert artifact["user_id"] == "user-one-123"
    assert artifact["session_id"] == session["id"]
    assert artifact["sources"][0]["source_id"] == "S1"
    listed = client.get("/api/v1/artifacts", params={"user_id": "user-one-123"})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == artifact["id"]


def test_ship30_refuses_to_create_artifact_without_evidence(client):
    session = create_session(client, "user-one-123")
    empty = Answer("I could not find sufficient evidence.", [], False)
    app.dependency_overrides[get_claude_research_agent] = lambda: StubEssayAgent(empty)
    response = client.post("/api/v1/artifacts/ship30", json={"user_id": "user-one-123", "session_id": session["id"], "topic": "Customer research"})
    assert response.status_code == 422


def test_ship30_word_count_excludes_html_style_and_script():
    from app.api.routes.artifacts import _artifact_word_count
    assert _artifact_word_count("<style>.x { color: red }</style><h1>Useful essay</h1><script>ignore these words</script><p>For builders.</p>", "html") == 4


def test_ship30_markdown_word_count_excludes_markup_and_code():
    from app.api.routes.artifacts import _artifact_word_count
    assert _artifact_word_count("# Useful essay\n\nRead [this guide](https://example.test). `inline code`\n```js\nconst hidden = true\n```", "markdown") == 3


def test_database_failure_maps_to_service_unavailable(client):
    def failed_db():
        raise OperationalError("select 1", {}, RuntimeError("database secret"))
        yield

    app.dependency_overrides[get_db] = failed_db
    response = client.post("/api/v1/chat/sessions", json={"user_id": "user-one-123"})
    assert response.status_code == 503
    assert "database secret" not in response.text
