import json
import logging
import sys
from types import SimpleNamespace

from app.core import rag_diagnostics
from app.core.logging_config import JsonFormatter


def test_rag_diagnostics_are_disabled_by_default(monkeypatch, caplog):
    monkeypatch.setattr(rag_diagnostics, "get_settings", lambda: SimpleNamespace(rag_diagnostics=False))
    with caplog.at_level(logging.INFO):
        rag_diagnostics.log_rag_diagnostic(logging.getLogger("test.rag"), "rag_test", raw_count=5)
    assert caplog.records == []


def test_rag_diagnostics_correlate_request_and_formatter_omits_unapproved_fields(monkeypatch, caplog):
    monkeypatch.setattr(rag_diagnostics, "get_settings", lambda: SimpleNamespace(rag_diagnostics=True))
    token = rag_diagnostics.request_id_context.set("request-test")
    try:
        with caplog.at_level(logging.INFO, logger="test.rag"):
            rag_diagnostics.log_rag_diagnostic(
                logging.getLogger("test.rag"), "rag_test", raw_count=5,
                transcript_text="must not appear in logs",
            )
    finally:
        rag_diagnostics.request_id_context.reset(token)

    payload = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert payload["request_id"] == "request-test"
    assert payload["raw_count"] == 5
    assert "transcript_text" not in payload


def test_json_formatter_includes_safe_exception_chain_and_traceback(caplog):
    logger = logging.getLogger("test.provider")
    try:
        try:
            raise TimeoutError("socket timed out; password=super-secret")
        except TimeoutError as cause:
            raise RuntimeError("Ollama request failed at https://user:secret@localhost:11434") from cause
    except RuntimeError:
        with caplog.at_level(logging.ERROR, logger="test.provider"):
            logger.exception("RAG answer generation stage failed", extra={"event": "rag_stage_failed", "stage": "generate"})

    payload = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert payload["stage"] == "generate"
    assert payload["exceptions"][0]["type"] == "RuntimeError"
    assert "user:secret" not in json.dumps(payload)
    assert "super-secret" not in json.dumps(payload)
    assert "timed out" in json.dumps(payload)
    assert payload["traceback"]
    assert "transcript" not in json.dumps(payload).lower()


def test_rag_stage_failures_are_logged_even_when_success_diagnostics_are_disabled(monkeypatch, caplog):
    from app.rag.retrieval import Retriever
    from app.services.rag import RAGService

    monkeypatch.setattr(rag_diagnostics, "get_settings", lambda: SimpleNamespace(rag_diagnostics=False))

    class FailingEmbeddings:
        def embed(self, _texts):
            raise RuntimeError("Ollama embedding request failed")

    class UnusedStore:
        def query(self, *_args):
            raise AssertionError("Chroma query must not run when embedding fails")

    class UnusedLLM:
        def generate(self, *_args):
            raise AssertionError("LLM generation must not run when retrieval fails")

    token = rag_diagnostics.request_id_context.set("request-failure-test")
    try:
        with caplog.at_level(logging.ERROR, logger="app.services.rag"):
            try:
                RAGService(Retriever(UnusedStore(), FailingEmbeddings()), UnusedLLM()).answer("question")
            except RuntimeError:
                pass
            else:
                raise AssertionError("Expected the embedding failure to propagate")
    finally:
        rag_diagnostics.request_id_context.reset(token)

    failure = next(record for record in caplog.records if getattr(record, "event", None) == "rag_stage_failed")
    payload = json.loads(JsonFormatter().format(failure))
    assert payload["request_id"] == "request-failure-test"
    assert payload["stage"] == "retrieve"
    assert payload["exceptions"][0]["message"] == "Ollama embedding request failed"


def test_request_middleware_correlates_sync_endpoint_failures(caplog):
    from fastapi import Request
    from fastapi.testclient import TestClient
    from app.main import app

    @app.get("/diagnostic-sync-failure")
    def sync_failure(request: Request):
        token = rag_diagnostics.request_id_context.set(request.state.request_id)
        try:
            try:
                raise RuntimeError("diagnostic sync failure")
            except RuntimeError as exc:
                rag_diagnostics.log_rag_failure(logging.getLogger("test.sync"), "sync endpoint failed", stage="retrieve", exc=exc)
        finally:
            rag_diagnostics.request_id_context.reset(token)
        return {"request_id": request.state.request_id}

    try:
        with TestClient(app) as client:
            response = client.get("/diagnostic-sync-failure")
        assert response.status_code == 200
        request_id = response.headers["X-Request-ID"]
        assert response.json()["request_id"] == request_id
        failure = next(record for record in caplog.records if getattr(record, "event", None) == "rag_stage_failed")
        assert failure.request_id == request_id
    finally:
        app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/diagnostic-sync-failure"]
