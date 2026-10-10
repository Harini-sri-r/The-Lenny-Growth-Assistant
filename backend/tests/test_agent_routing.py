import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.core.config import Settings
from app.services import container
from app.services.rag import RAGService


def test_config_defaults_to_claude_agent_sdk():
    assert Settings(_env_file=None).agent_framework == "claude_agent_sdk"


def test_config_can_select_local_rag_service():
    assert Settings(_env_file=None, agent_framework="rag_service", llm_provider="ollama").agent_framework == "rag_service"


def test_config_uses_available_local_ollama_model_and_safe_database_default():
    settings = Settings(_env_file=None)
    assert settings.ollama_model == "llama3:latest"
    assert settings.effective_database_url == "postgresql+psycopg://lenny:example_password@localhost:5432/lenny"


def test_environment_file_path_is_independent_of_working_directory(tmp_path, monkeypatch):
    from app.core.config import ENV_FILE, PROJECT_ROOT

    monkeypatch.chdir(tmp_path)

    assert ENV_FILE.is_absolute()
    assert ENV_FILE.name == ".env"
    assert ENV_FILE.parent == Path(__file__).resolve().parents[2]
    settings = Settings(_env_file=None, chroma_persist_directory="./chroma", transcripts_path="./transcripts")
    assert settings.chroma_persist_directory == PROJECT_ROOT / "chroma"
    assert settings.transcripts_path == PROJECT_ROOT / "transcripts"


def test_chat_service_factory_selects_claude_agent(monkeypatch):
    retriever = object()
    monkeypatch.setattr(container, "get_settings", lambda: Settings(_env_file=None, agent_framework="claude_agent_sdk"))
    monkeypatch.setattr(container, "get_retriever", lambda: retriever)
    created = {}

    class FakeClaudeAgent:
        def __init__(self, actual_retriever, *, model, max_turns):
            created.update(retriever=actual_retriever, model=model, max_turns=max_turns)

    monkeypatch.setattr(container, "ClaudeResearchAgent", FakeClaudeAgent)
    service = container.get_rag_service()
    assert isinstance(service, FakeClaudeAgent)
    assert created == {"retriever": retriever, "model": "sonnet", "max_turns": 5}


def test_chat_service_factory_preserves_local_ollama_rag(monkeypatch):
    retriever, provider = object(), object()
    monkeypatch.setattr(container, "get_settings", lambda: Settings(_env_file=None, agent_framework="rag_service", llm_provider="ollama"))
    monkeypatch.setattr(container, "get_retriever", lambda: retriever)
    monkeypatch.setattr(container, "create_llm_provider", lambda _settings: provider)
    service = container.get_rag_service()
    assert isinstance(service, RAGService)
    assert service.retriever is retriever
    assert service.llm is provider


def test_chat_service_factory_rejects_unknown_framework(monkeypatch):
    monkeypatch.setattr(container, "get_settings", lambda: Settings(_env_file=None, agent_framework="unknown"))
    with pytest.raises(RuntimeError, match="Unsupported AGENT_FRAMEWORK"):
        container.get_rag_service()


def test_chat_service_factory_sanitizes_and_logs_retriever_initialization_failure(monkeypatch, caplog):
    monkeypatch.setattr(container, "get_settings", lambda: Settings(_env_file=None, agent_framework="rag_service"))
    def fail():
        raise RuntimeError("private local storage path")
    monkeypatch.setattr(container, "get_retriever", fail)
    with pytest.raises(RuntimeError, match="LLM provider configuration") as error:
        container.get_rag_service()
    assert "private local storage path" not in str(error.value)
    assert "private local storage path" in caplog.text

