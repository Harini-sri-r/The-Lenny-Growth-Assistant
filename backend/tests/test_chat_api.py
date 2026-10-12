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
from app.api.routes.artifacts import _ship30_request_parts


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


def test_ship30_request_parser_uses_title_and_drops_pasted_ui_error():
    title = "The Activation Moment: Turning New Users into Engaged Customers"
    pasted_request = (
        "Essay generation failed: The transcript library did not return enough evidence. "
        f'Create a Ship 30 essay titled "{title}". '
        "Use the activation strategies discussed in our conversation."
    )

    parsed_title, instructions = _ship30_request_parts(pasted_request)

    assert parsed_title == title
    assert instructions.startswith("Use the activation strategies")
    assert "generation failed" not in instructions.lower()


def test_ship30_request_parser_extracts_markdown_emphasized_title_and_instructions():
    title = "From Zero to Product-Market Fit: Lessons Every Startup Founder Should Know."
    pasted_request = f'Create a Ship 30 essay titled **"{title}"** Explain how early-stage teams should find fit.'

    parsed_title, instructions = _ship30_request_parts(pasted_request)

    assert parsed_title == title
    assert instructions == "Explain how early-stage teams should find fit"


def test_ship30_uses_extracted_title_for_retrieval_and_generation(client):
    title = "The Activation Moment: Turning New Users into Engaged Customers"
    captured = {}

    class CapturingEssayAgent:
        def answer(self, prompt, *, system_prompt=None, retrieval_query=None):
            captured.update(prompt=prompt, retrieval_query=retrieval_query)
            return StubEssayAgent().result

    app.dependency_overrides[get_claude_research_agent] = lambda: CapturingEssayAgent()
    session = create_session(client, "user-one-123")
    topic = (
        "Essay generation failed: no evidence. "
        f'Create a Ship 30 essay titled "{title}". '
        "Use the activation strategies discussed in our conversation."
    )

    response = client.post("/api/v1/artifacts/ship30", json={
        "session_id": session["id"], "topic": topic,
    })

    assert response.status_code == 201
    assert captured["retrieval_query"] == title
    assert "Essay generation failed" not in captured["prompt"]
    assert f'titled "{title}"' in captured["prompt"]


class StubEssayAgent:
    def __init__(self, answer=None):
        self.result = answer or Answer(
            answer="# A useful grounded essay\n\n" + " ".join(
                ["Product teams should test their assumptions with customers. [S1]"] * 130
            ),
            grounded=True,
            sources=[SourceReference("S1", "Sample episode", "podcast", "podcasts/sample.md", "https://example.test/episode", "chunk-1")],
        )

    def answer(self, prompt, *, system_prompt=None, retrieval_query=None):
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
        registered = test_client.post("/api/v1/auth/register", json={"email": "owner@example.test", "password": "correct horse battery staple"})
        assert registered.status_code == 201
        signed_in = test_client.post("/api/v1/auth/login", json={"email": "owner@example.test", "password": "correct horse battery staple"})
        assert signed_in.status_code == 200
        test_client.headers["X-CSRF-Token"] = test_client.cookies.get("lenny_csrf", "")
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
    other_credentials = {"email": "other@example.test", "password": "another secure password"}
    assert client.post("/api/v1/auth/register", json=other_credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json=other_credentials).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("lenny_csrf", "")
    other_user = create_session(client, "user-two-456")
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.test", "password": "correct horse battery staple"}).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("lenny_csrf", "")
    assert first["id"] != second["id"]
    assert first["created_at"] and first["updated_at"]

    listed = client.get("/api/v1/chat/sessions", params={"user_id": "user-one-123"})
    assert listed.status_code == 200
    assert any(item["id"] == first["id"] for item in listed.json())

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
    assert client.get(f"/api/v1/chat/sessions/{other_user['id']}/messages").status_code == 404
    assert other_user["user_id"] != first["user_id"]


def test_first_meaningful_message_sets_and_persists_session_title(client):
    session = create_session(client, "ignored-client-user")
    greeting = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"message": "Hello there!"})
    assert greeting.status_code == 200
    assert greeting.json()["session"]["title"] == "New chat"

    meaningful = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={
        "message": "What are the best ways to improve user onboarding?",
    })
    assert meaningful.status_code == 200
    assert meaningful.json()["session"]["title"] == "Improving User Onboarding"

    renamed = client.patch(f"/api/v1/chat/sessions/{session['id']}", json={"title": "My onboarding notes"})
    assert renamed.status_code == 200
    later = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"message": "How should we improve retention?"})
    assert later.status_code == 200
    assert later.json()["session"]["title"] == "My onboarding notes"
    assert client.get("/api/v1/chat/sessions").json()[0]["title"] == "My onboarding notes"


def test_duplicate_titles_remain_attached_to_distinct_sessions(client):
    sessions = [create_session(client, "ignored-client-user") for _ in range(2)]
    titles = []
    for session in sessions:
        response = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"message": "How to find product-market fit"})
        assert response.status_code == 200
        titles.append(response.json()["session"]["title"])
    assert titles == ["Finding Product-Market Fit", "Finding Product-Market Fit"]
    saved = {item["id"]: item["title"] for item in client.get("/api/v1/chat/sessions").json()}
    assert all(saved[session["id"]] == "Finding Product-Market Fit" for session in sessions)


def test_send_message_rejects_nonexistent_or_other_users_session(client):
    missing_id = "00000000-0000-0000-0000-000000000000"
    missing = client.post(
        f"/api/v1/chat/sessions/{missing_id}/messages",
        json={"user_id": "user-one-123", "message": "Question"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Chat session not found"

    other_credentials = {"email": "other2@example.test", "password": "another secure password"}
    assert client.post("/api/v1/auth/register", json=other_credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json=other_credentials).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("lenny_csrf", "")
    owned_by_other = create_session(client, "user-two-456")
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.test", "password": "correct horse battery staple"}).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("lenny_csrf", "")
    forbidden = client.post(
        f"/api/v1/chat/sessions/{owned_by_other['id']}/messages",
        json={"user_id": "user-one-123", "message": "Question"},
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["detail"] == "Chat session not found"
    forbidden_rename = client.patch(f"/api/v1/chat/sessions/{owned_by_other['id']}", json={"title": "Hijacked title"})
    assert forbidden_rename.status_code == 404


def test_session_rename_delete_and_message_retry_are_persisted_once(client):
    session = create_session(client, "ignored-client-user")
    changed = client.patch(f"/api/v1/chat/sessions/{session['id']}", json={"title": "Retention strategy"})
    assert changed.status_code == 200
    assert changed.json()["title"] == "Retention strategy"
    request = {"message": "How can I improve retention?", "client_message_id": "stable-request-0001"}
    first = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json=request)
    retry = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json=request)
    assert first.status_code == retry.status_code == 200
    assert first.json()["assistant_message"]["id"] == retry.json()["assistant_message"]["id"]
    assert len(client.get(f"/api/v1/chat/sessions/{session['id']}/messages").json()) == 2
    assert client.delete(f"/api/v1/chat/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/v1/chat/sessions/{session['id']}/messages").status_code == 404


def test_followup_rag_request_includes_only_this_sessions_prior_context(client):
    captured = []

    class CaptureRAG:
        def answer(self, question):
            captured.append(question)
            return StubRAG().answer(question)

    app.dependency_overrides[get_rag_service] = lambda: CaptureRAG()
    session = create_session(client, "ignored-client-user")
    for text in ("We are investigating user activation", "What about retention?"):
        response = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"message": text})
        assert response.status_code == 200
    assert "Earlier conversation" in captured[1]
    assert "We are investigating user activation" in captured[1]
    assert "Current question: What about retention?" in captured[1]


def test_provider_failure_returns_safe_503_and_keeps_user_message(client):
    app.dependency_overrides[get_rag_service] = lambda: StubRAG(RuntimeError("private machine details"))
    session = create_session(client, "user-one-123")
    request = {"user_id": "user-one-123", "message": "Question", "client_message_id": "request-key-0001"}
    response = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json=request)
    assert response.status_code == 503
    assert "private machine details" not in response.text
    assert client.get("/api/v1/chat/sessions").json()[0]["title"] == "Question"
    history = client.get(f"/api/v1/chat/sessions/{session['id']}/messages", params={"user_id": "user-one-123"})
    assert [message["role"] for message in history.json()] == ["user"]
    app.dependency_overrides[get_rag_service] = lambda: StubRAG()
    retry = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json=request)
    assert retry.status_code == 200
    assert len(client.get(f"/api/v1/chat/sessions/{session['id']}/messages").json()) == 2


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
    assert artifact["user_id"] == session["user_id"]
    assert artifact["session_id"] == session["id"]
    assert artifact["sources"][0]["source_id"] == "S1"
    listed = client.get("/api/v1/artifacts", params={"user_id": "user-one-123"})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == artifact["id"]


def test_conversation_artifact_uses_history_and_persists_grounded_html(client):
    captured = {}

    class ConversationArtifactAgent:
        def answer(self, prompt, *, system_prompt=None, retrieval_query=None):
            captured.update(prompt=prompt, system_prompt=system_prompt, retrieval_query=retrieval_query)
            return Answer(
                '<h1>Retention strategy</h1><p>Help users reach value early [S1].</p>',
                grounded=True,
                sources=[SourceReference("S1", "Retention episode", "podcast", "podcasts/retention.md", "https://example.test/retention", "retention-1")],
            )

    session = create_session(client, "user-one-123")
    sent = client.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={
        "user_id": "user-one-123", "message": "What makes new users return?",
    })
    assert sent.status_code == 200
    app.dependency_overrides[get_rag_service] = lambda: ConversationArtifactAgent()

    response = client.post("/api/v1/artifacts/from-chat", json={
        "session_id": session["id"],
        "request": "Create a concise retention strategy page",
        "artifact_format": "html",
    })

    assert response.status_code == 201
    saved = response.json()
    assert captured["retrieval_query"].startswith("Create a concise retention strategy page")
    assert "What makes new users return?" in captured["prompt"]
    assert "Treat conversation history" in captured["system_prompt"]
    assert saved["title"] == "Retention strategy"
    assert saved["content"].startswith("<!doctype html>")
    assert "Help users reach value early [S1]." in saved["content"]
    assert saved["sources"][0]["source_id"] == "S1"
    assert saved["word_count"] > 0
    assert client.get("/api/v1/artifacts").json()[0]["id"] == saved["id"]


def test_conversation_artifact_rejects_ungrounded_output_without_saving(client):
    class UngroundedAgent:
        def answer(self, *_args, **_kwargs):
            return Answer("Unsupported content", [], False, "no_topic_evidence")

    app.dependency_overrides[get_rag_service] = lambda: UngroundedAgent()
    session = create_session(client, "user-one-123")

    response = client.post("/api/v1/artifacts/from-chat", json={
        "session_id": session["id"], "request": "Create a strategy document",
    })

    assert response.status_code == 422
    assert client.get("/api/v1/artifacts").json() == []


def test_ship30_retention_topic_generates_from_relevant_retrieved_evidence(client):
    captured = {}

    class RelevantRetentionAgent:
        def answer(self, prompt, *, system_prompt=None, retrieval_query=None):
            captured.update(prompt=prompt, system_prompt=system_prompt, retrieval_query=retrieval_query)
            return Answer(
                answer=(
                    "# Help users come back\n\n"
                    "Start by tracking D7 retention and using the product as a new customer to find first-use friction. [S1]\n\n"
                    + " ".join([
                        "The source says early retention remains important and recommends signing up from scratch to dogfood the experience. [S1]"
                    ] * 70)
                ),
                grounded=True,
                sources=[SourceReference(
                    "S1", "The power user’s guide to Codex", "podcast", "podcasts/alexander-embiricos.md",
                    "https://example.test/episode", "retention-chunk-1",
                )],
            )

    app.dependency_overrides[get_claude_research_agent] = lambda: RelevantRetentionAgent()
    session = create_session(client, "user-one-123")
    topic = "How startups can improve user retention by building products people love"
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": topic,
        "audience": "product managers and startup operators", "artifact_format": "markdown",
    })

    assert response.status_code == 201
    artifact = response.json()
    assert artifact["session_id"] == session["id"]
    assert "D7 retention" in artifact["content"]
    assert artifact["sources"][0]["chunk_id"] == "retention-chunk-1"
    assert topic in captured["prompt"]
    assert "Target approximately 1,250 words" in captured["prompt"]
    assert "Write one useful, clear essay" in captured["system_prompt"]
    assert "strong opening hook" in captured["system_prompt"]
    assert "narrative progression" in captured["system_prompt"]
    assert "skimmable headings" in captured["system_prompt"]
    assert "concise takeaway" in captured["system_prompt"]
    assert captured["retrieval_query"] == topic


def test_ship30_saves_honest_source_search_note_without_evidence(client, caplog):
    session = create_session(client, "user-one-123")
    empty = Answer("I could not find sufficient evidence.", [], False, "no_topic_evidence")
    app.dependency_overrides[get_claude_research_agent] = lambda: StubEssayAgent(empty)
    response = client.post("/api/v1/artifacts/ship30", json={"user_id": "user-one-123", "session_id": session["id"], "topic": "Customer research"})
    assert response.status_code == 201
    artifact = response.json()
    assert artifact["sources"] == []
    assert "did not return relevant passages" in artifact["content"]
    assert "Try a narrower topic" in artifact["content"]
    rejection = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_rejected")
    assert rejection.reason == "no_topic_evidence"
    assert rejection.topic_chars == len("Customer research")


def test_ship30_timeout_returns_504_without_saving_artifact(client):
    from app.agents.providers import OllamaTimeoutError

    class TimedOutEssayAgent:
        def __init__(self):
            self.calls = 0

        def answer(self, *_args, **_kwargs):
            self.calls += 1
            raise OllamaTimeoutError("Ollama did not respond within 180 seconds.")

    agent = TimedOutEssayAgent()
    app.dependency_overrides[get_claude_research_agent] = lambda: agent
    session = create_session(client, "user-one-123")
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": "Customer research",
    })

    assert response.status_code == 504
    assert "180 seconds" in response.json()["detail"]
    assert agent.calls == 1
    assert client.get("/api/v1/artifacts", params={"user_id": "user-one-123"}).json() == []


def test_ship30_tiny_grounded_draft_is_not_mislabeled_as_a_usable_essay(client):
    short_answer = Answer(
        "# Retention\n\nTrack D7 retention to understand continued use. [S1]",
        [SourceReference("S1", "Retention", "podcast", "podcasts/retention.md", None, "retention-1")],
        True,
    )
    app.dependency_overrides[get_claude_research_agent] = lambda: StubEssayAgent(short_answer)
    session = create_session(client, "user-one-123")
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": "Customer research",
    })

    assert response.status_code == 503
    assert "minimum length" in response.json()["detail"] or "requires at least" in response.json()["detail"]


def test_ship30_endpoint_rejects_tiny_grounded_answer(client, caplog):
    from app.core.config import get_settings
    get_settings.cache_clear()
    short_answer = Answer(
        "# Retention\n\nTrack D7 retention to understand continued use. [S1]",
        [SourceReference("S1", "Retention", "podcast", "podcasts/retention.md", None, "retention-1")],
        True,
    )
    app.dependency_overrides[get_claude_research_agent] = lambda: StubEssayAgent(short_answer)
    session = create_session(client, "user-one-123")
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": "Retention",
    })
    assert response.status_code == 503
    assert "minimum length" in response.json()["detail"] or "requires at least" in response.json()["detail"]


def test_ship30_endpoint_deduplicates_essay_before_persisting_artifact(client, monkeypatch):
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr("app.api.routes.artifacts.get_settings", lambda: type("Settings", (), {
        "agent_framework": "rag_service", "ship30_minimum_response_words": 1150,
        "llm_provider": "ollama",
    })())
    paragraphs = [
        f"Teams can learn from cohort {index} customers before choosing a practical solution for retention. [S1]"
        for index in range(1, 151)
    ]
    one_essay = "# A grounded retention essay\n\n" + "\n\n".join(paragraphs)
    app.dependency_overrides[get_claude_research_agent] = lambda: StubEssayAgent(Answer(
        one_essay + "\n\n" + one_essay,
        [SourceReference("S1", "Retention", "podcast", "podcasts/retention.md", None, "retention-1")],
        True,
    ))
    session = create_session(client, "user-one-123")
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": "Retention",
    })
    assert response.status_code == 201
    saved = response.json()["content"]
    assert saved.count("# A grounded retention essay") == 1
    assert all(saved.count(paragraph) <= 1 for paragraph in paragraphs)
    assert any(saved.count(paragraph) == 1 for paragraph in paragraphs)
    assert 1150 <= response.json()["word_count"] <= 1350
    assert 1150 <= response.json()["word_count"] <= 1350


@pytest.mark.parametrize(("failure", "status", "message"), [
    ("unavailable", 503, "Ollama is unavailable"),
    ("timeout", 504, "did not respond within"),
    ("generation", 503, "Ollama could not generate the essay"),
    ("truncated", 503, "output token limit before completing"),
    ("retrieval_timeout", 504, "selected provider timed out while retrieving evidence"),
    ("generic", 503, "Essay generation failed"),
])
def test_ship30_reports_local_generation_failures_safely(client, caplog, failure, status, message):
    from app.agents.providers import OllamaGenerationError, OllamaTimeoutError, OllamaTruncatedResponseError, OllamaUnavailableError

    failures = {
        "unavailable": OllamaUnavailableError("Ollama is unavailable. Start Ollama and confirm llama3:latest is installed."),
        "timeout": OllamaTimeoutError("Ollama did not respond within 240 seconds. Check the local model."),
        "generation": OllamaGenerationError("Ollama could not complete generation; private response body"),
        "truncated": OllamaTruncatedResponseError(),
        "retrieval_timeout": RuntimeError("Ollama embedding request failed: timed out"),
        "generic": RuntimeError("private provider response and prompt text"),
    }
    secret = "private provider response"

    class FailedEssayAgent:
        def answer(self, *_args, **_kwargs):
            raise failures[failure]

    app.dependency_overrides[get_claude_research_agent] = lambda: FailedEssayAgent()
    session = create_session(client, "user-one-123")
    response = client.post("/api/v1/artifacts/ship30", json={
        "user_id": "user-one-123", "session_id": session["id"], "topic": "Customer research",
    })

    assert response.status_code == status
    assert message in response.json()["detail"]
    assert secret not in response.text
    assert secret not in caplog.text
    assert client.get("/api/v1/artifacts", params={"user_id": "user-one-123"}).json() == []
    failed = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_failed")
    assert failed.error_type in {type(error).__name__ for error in failures.values()}


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
