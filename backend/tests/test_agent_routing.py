import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.core.config import Settings
from app.services import container
from app.services.rag import RAGService


def test_config_defaults_to_local_ollama_rag_service():
    settings = Settings(_env_file=None)
    assert settings.agent_framework == "rag_service"
    assert settings.llm_provider == "ollama"


def test_env_example_keeps_ollama_as_the_local_default():
    from app.core.config import PROJECT_ROOT

    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LLM_PROVIDER=ollama" in example
    assert "AGENT_FRAMEWORK=rag_service" in example
    assert "SHIP30_MAX_OUTPUT_TOKENS=3000" in example
    assert "SHIP30_MINIMUM_RESPONSE_WORDS=1000" in example
    assert "SHIP30_MAX_CONTINUATIONS=3" in example


def test_config_loads_anthropic_key_from_env_file_without_exporting_it(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=test-only-fake-key\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.anthropic_api_key == "test-only-fake-key"
    assert "ANTHROPIC_API_KEY" not in __import__("os").environ


def test_config_loads_gemini_settings_from_env_file_without_exporting_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-only-gemini-key\nGEMINI_MODEL=gemini-test\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=env_file)
    assert settings.gemini_api_key == "test-only-gemini-key"
    assert settings.gemini_model == "gemini-test"
    assert "GEMINI_API_KEY" not in __import__("os").environ


def test_config_can_select_local_rag_service():
    assert Settings(_env_file=None, agent_framework="rag_service", llm_provider="ollama").agent_framework == "rag_service"


@pytest.mark.parametrize(("provider", "model", "key"), [("ollama", "llama3:latest", ""), ("gemini", "gemini-test", "test-gemini-key")])
def test_pi_framework_routes_selected_models_without_python_provider_fallback(monkeypatch, provider, model, key):
    from app.agents.lenny_agent import PiCodingAgent
    settings = Settings(_env_file=None, agent_framework="pi_coding_agent", llm_provider=provider,
                        ollama_model="llama3:latest", gemini_model="gemini-test", gemini_api_key=key)
    retriever = object()
    monkeypatch.setattr(container, "get_settings", lambda: settings)
    monkeypatch.setattr(container, "get_retriever", lambda: retriever)
    agent = container.get_rag_service()
    assert isinstance(agent, PiCodingAgent)
    assert (agent.provider, agent.model) == (provider, model)
    ship30 = container.get_claude_research_agent()
    assert isinstance(ship30, PiCodingAgent)
    assert (ship30.provider, ship30.model) == (provider, model)


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
    assert Settings.model_config["env_file"] == ENV_FILE == PROJECT_ROOT / ".env"
    settings = Settings(_env_file=None, chroma_persist_directory="./chroma", transcripts_path="./transcripts")
    assert settings.chroma_persist_directory == PROJECT_ROOT / "chroma"
    assert settings.transcripts_path == PROJECT_ROOT / "transcripts"


def test_chat_service_factory_selects_claude_agent(monkeypatch):
    retriever = object()
    fake_key = "test-only-fake-key"
    monkeypatch.setattr(container, "get_settings", lambda: Settings(_env_file=None, agent_framework="claude_agent_sdk", anthropic_api_key=fake_key))
    monkeypatch.setattr(container, "get_retriever", lambda: retriever)
    created = {}

    class FakeClaudeAgent:
        def __init__(self, actual_retriever, *, model, max_turns, anthropic_api_key=""):
            created.update(retriever=actual_retriever, model=model, max_turns=max_turns, anthropic_api_key=anthropic_api_key)

    monkeypatch.setattr(container, "ClaudeResearchAgent", FakeClaudeAgent)
    service = container.get_rag_service()
    assert isinstance(service, container._OllamaFallbackAgent)
    assert isinstance(service.cloud_agent, FakeClaudeAgent)
    assert created == {"retriever": retriever, "model": "sonnet", "max_turns": 5, "anthropic_api_key": fake_key}


def test_chat_service_uses_ollama_when_claude_credentials_are_missing(monkeypatch):
    from app.agents.providers import OllamaProvider

    retriever = object()
    settings = Settings(_env_file=None, agent_framework="claude_agent_sdk", anthropic_api_key="")
    monkeypatch.setattr(container, "get_settings", lambda: settings)
    monkeypatch.setattr(container, "get_retriever", lambda: retriever)
    service = container.get_rag_service()
    assert isinstance(service, RAGService)
    assert isinstance(service.llm, OllamaProvider)


def test_chat_and_ship30_route_gemini_through_selected_provider_factory(monkeypatch):
    settings = Settings(_env_file=None, agent_framework="rag_service", llm_provider="gemini", gemini_api_key="test-key")
    retriever = object()
    calls = []
    class FakeProvider:
        def generate(self, *_args): return ""
    monkeypatch.setattr(container, "get_settings", lambda: settings)
    monkeypatch.setattr(container, "get_retriever", lambda: retriever)
    def create_provider(actual_settings, **kwargs):
        calls.append((actual_settings, kwargs))
        return FakeProvider()
    monkeypatch.setattr(container, "create_llm_provider", create_provider)

    chat_service = container.get_rag_service()
    ship30_agent = container.get_claude_research_agent()
    assert isinstance(chat_service, RAGService)
    assert isinstance(chat_service.llm, FakeProvider)
    assert isinstance(ship30_agent.local_agent.llm, FakeProvider)
    assert len(calls) == 2
    assert calls[0][1] == {}
    assert calls[1][1] == {
        "max_response_tokens": 3000, "ollama_timeout": 180,
        "provider_timeout": 180, "ollama_reject_truncated": False, "fallback": False,
    }


def test_claude_failure_falls_back_to_grounded_ollama_without_logging_secrets(monkeypatch, caplog):
    from app.rag.retrieval import Passage

    secret = "fake-cloud-secret-never-log"
    passage = Passage("Interview customers before committing to a solution.", {
        "source_path": "podcasts/research.md", "chunk_id": "research-1", "title": "Research", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class FakeOllama:
        def generate(self, _system, _user): return "Interview customers before committing to a solution. [S1]"

    class FailingCloudAgent:
        def __init__(self, *_args, **_kwargs): pass
        def answer(self, *_args, **_kwargs): raise RuntimeError(secret)

    settings = Settings(_env_file=None, agent_framework="claude_agent_sdk", anthropic_api_key="test-cloud-key")
    monkeypatch.setattr(container, "get_settings", lambda: settings)
    monkeypatch.setattr(container, "get_retriever", lambda: FakeRetriever())
    monkeypatch.setattr(container, "ClaudeResearchAgent", FailingCloudAgent)
    monkeypatch.setattr(container, "create_ollama_provider", lambda *_args, **_kwargs: FakeOllama())

    service = container.get_rag_service()
    answer = service.answer("customer research")

    assert answer.grounded is True
    assert answer.sources[0].source_path == "podcasts/research.md"
    assert secret not in caplog.text
    assert "cloud_agent_fallback_to_ollama" in caplog.text


def test_ship30_uses_local_ollama_when_framework_is_local(monkeypatch):
    from app.rag.retrieval import Passage

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, query):
            assert query == "retention topic"
            return [passage]

    class FakeOllama:
        def __init__(self): self.prompts = []
        def generate(self, system_prompt, user_prompt):
            self.prompts.append((system_prompt, user_prompt))
            return "# Retention begins with first use\n\n## Find the early friction\n\n" + " ".join(
                ["Track D7 retention to understand continued use. [S1]"] * 185
            ) + "\n\n## Takeaway\n\nTeams can use this measure to understand continued use. [S1]"

    settings = Settings(_env_file=None, agent_framework="rag_service", llm_provider="ollama")
    fake_ollama = FakeOllama()
    monkeypatch.setattr(container, "get_settings", lambda: settings)
    monkeypatch.setattr(container, "get_retriever", FakeRetriever)
    created = {}
    def fake_create_provider(*args, **kwargs):
        created.update(args=args, kwargs=kwargs)
        return fake_ollama
    monkeypatch.setattr(container, "create_llm_provider", fake_create_provider)

    agent = container.get_claude_research_agent()
    answer = agent.answer(
        "Write an essay. Requested output: Markdown.",
        system_prompt="Use the read-only `search_transcripts` tool before drafting and retrieve evidence about the topic.",
        retrieval_query="retention topic",
    )

    assert answer.grounded is True
    assert isinstance(agent.local_agent.llm, FakeOllama)
    assert settings.ship30_max_output_tokens == 3000
    assert settings.ship30_max_continuations == 3
    assert settings.ship30_generation_timeout_seconds == 180
    assert created["kwargs"] == {
        "max_response_tokens": 3000, "ollama_timeout": 180,
        "provider_timeout": 180, "ollama_reject_truncated": False, "fallback": False,
    }
    assert agent.local_agent.max_context_passages == 5
    assert agent.local_agent.max_context_chars_per_passage == 1800
    assert agent.local_agent.preserve_markdown_structure is True
    assert agent.local_agent.compact_context is True
    assert agent.local_agent.minimum_response_words == 1150
    assert len(fake_ollama.prompts) == 1
    assert "approximately 1,250 words (1,150 to 1,350 words)" in fake_ollama.prompts[0][0]
    assert "Cite every factual sentence" in fake_ollama.prompts[0][0]
    assert "citation at the end of each sentence" in fake_ollama.prompts[0][0]
    assert "Omit any sentence you cannot directly support" in fake_ollama.prompts[0][0]
    assert "Available citation labels: [S1]" in fake_ollama.prompts[0][1]
    assert "[S1] Retention\nTrack D7 retention" in fake_ollama.prompts[0][1]
    assert "Search the transcript knowledge tool" not in fake_ollama.prompts[0][1]

    html_answer = agent.answer(
        "Write an essay. Requested output: self-contained HTML with inline CSS and no JavaScript or remote resources.",
        system_prompt="Use the read-only `search_transcripts` tool before drafting and retrieve evidence about the topic.",
        retrieval_query="retention topic",
    )
    assert html_answer.grounded is True
    assert html_answer.answer.startswith("<!doctype html>")
    assert "[S1]" in html_answer.answer
    assert len(fake_ollama.prompts) == 2
    assert "Requested output: Markdown." in fake_ollama.prompts[1][1]


def test_local_ship30_keeps_markdown_structure_and_requires_citations_for_claims():
    from app.rag.retrieval import Passage

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class EssayLLM:
        def generate(self, _system, _user):
            return "# A useful opening\n\n## Start with the first week\n\nTrack D7 retention to understand continued use. [S1]\n\nThis guarantees growth for every company."

    answer = RAGService(FakeRetriever(), EssayLLM(), preserve_markdown_structure=True).answer("retention essay")

    assert answer.grounded is True
    assert "# A useful opening" in answer.answer
    assert "## Start with the first week" in answer.answer
    assert "Track D7 retention to understand continued use. [S1]" in answer.answer
    assert "guarantees growth" not in answer.answer


def test_ship30_single_call_preserves_citations_and_drops_unsupported_claims():
    from app.rag.retrieval import Passage

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class OneCallLLM:
        def __init__(self): self.requests = []
        def generate(self, _system, user_prompt):
            self.requests.append(user_prompt)
            factual_line = "Track D7 retention to understand continued use. [S1]"
            unsupported = "The method guarantees success for every company."
            return "# A useful retention essay\n\n## Start with a measurable signal\n\n" + " ".join([factual_line] * 36) + f" {unsupported}\n\n## Takeaway\n\nTeams can use this measure to understand continued use. [S1]"

    llm = OneCallLLM()
    service = RAGService(FakeRetriever(), llm, preserve_markdown_structure=True, compact_context=True, minimum_response_words=170)
    answer = service.answer(
        "Write a retention essay for product teams.", retrieval_query="retention",
        system_prompt="Cite factual claims.",
    )

    assert answer.grounded is True
    assert len(llm.requests) == 1
    assert "# A useful retention essay" in answer.answer
    assert "## Start with a measurable signal" in answer.answer
    assert "## Takeaway" in answer.answer
    assert answer.answer.count("[S1]") == 37
    assert "guarantees success" not in answer.answer
    assert len(answer.sources) == 1 and answer.sources[0].source_id == "S1"
    assert "Available citation labels: [S1]" in llm.requests[0]
    assert "<source id=" not in llm.requests[0]


def test_ship30_valid_short_essay_passes_realistic_minimum_and_logs_safe_counts(caplog, monkeypatch):
    caplog.set_level("INFO")
    from app.rag.retrieval import Passage

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class ShortEssayLLM:
        def generate(self, _system, _user):
            sentence = "Track D7 retention to understand continued use. [S1]"
            return "# Retention starts with a signal\n\n## Watch what happens next\n\n" + " ".join([sentence] * 11)

    monkeypatch.setattr("app.core.rag_diagnostics.get_settings", lambda: type("Settings", (), {"rag_diagnostics": True})())
    service = RAGService(
        FakeRetriever(), ShortEssayLLM(), preserve_markdown_structure=True,
        compact_context=True, minimum_response_words=80,
    )
    answer = service.answer("Write a short retention essay.", system_prompt="Use citations.")

    assert answer.grounded is True
    assert len(answer.sources) == 1
    diagnostic = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_validation_passed")
    assert diagnostic.category == "grounded_minimum_met"
    assert 80 <= diagnostic.word_count < 100
    assert diagnostic.citation_count == 11
    assert not hasattr(diagnostic, "essay")


def test_ship30_genuinely_short_output_fails_with_safe_word_and_citation_counts(caplog):
    from app.rag.retrieval import Passage
    from app.services.rag import IncompleteEssayError

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class TooShortLLM:
        def generate(self, _system, _user):
            return "# Retention\n\nTrack D7 retention helps teams understand continued use. [S1]"

    service = RAGService(
        FakeRetriever(), TooShortLLM(), preserve_markdown_structure=True,
        compact_context=True, minimum_response_words=80,
    )
    with pytest.raises(IncompleteEssayError, match="no artifact was saved"):
        service.answer("Write about retention.", system_prompt="Use citations.")

    diagnostic = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_validation_failed")
    assert diagnostic.category == "insufficient_word_count"
    assert diagnostic.word_count < 80
    assert diagnostic.citation_count == 1
    assert "Track D7 retention" not in caplog.text


def test_gemini_ship30_short_response_fails_existing_validation_without_saving():
    from app.rag.retrieval import Passage
    from app.services.rag import IncompleteEssayError
    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)
    class FakeRetriever:
        def retrieve(self, _query): return [passage]
    class MockGeminiProvider:
        def generate(self, *_args): return "# Retention\n\nTeams track D7 to understand continued use. [S1]"
    service = RAGService(FakeRetriever(), MockGeminiProvider(), preserve_markdown_structure=True, minimum_response_words=80)
    with pytest.raises(IncompleteEssayError, match="no artifact was saved"):
        service.answer("Write a Ship 30 essay about retention.", system_prompt="Cite claims.")


def test_ship30_continues_short_truncated_gemini_once_and_keeps_only_valid_citations(caplog):
    caplog.set_level("INFO")
    from app.agents.providers import GenerationResult
    from app.rag.retrieval import Passage
    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)
    class FakeRetriever:
        def retrieve(self, _query): return [passage]
    fact = "Track D7 retention to understand continued use. [S1]"
    class SequenceGemini:
        provider_name, model_name = "gemini", "gemini-test"
        def __init__(self): self.requests = []
        def generate_with_metadata(self, _system, prompt):
            self.requests.append(prompt)
            if len(self.requests) == 1:
                return GenerationResult("# Retention essay\n\n## Start with a signal\n\nTeams should track D7. [S1]", "gemini", "gemini-test", 100, 20, True)
            body = " ".join([fact] * 185)
            return GenerationResult("# Retention essay\n\n## Start with a signal\n\n" + body + "\n\nRevenue doubled overnight. [S99]", "gemini", "gemini-test", 600, 2100, False)
    llm = SequenceGemini()
    service = RAGService(
        FakeRetriever(), llm, preserve_markdown_structure=True, compact_context=True,
        minimum_response_words=1000, target_response_words=1250, max_continuations=1,
    )

    answer = service.answer("Write a cited retention essay.", system_prompt="Use only the evidence.")

    assert answer.grounded is True
    assert len(llm.requests) == 2
    assert "Current citation-validated essay draft" in llm.requests[1]
    assert "Return only new paragraphs" in llm.requests[1]
    assert answer.answer.count("# Retention essay") == 1
    assert answer.answer.count("## Start with a signal") == 1
    assert "[S99]" not in answer.answer
    assert answer.sources[0].source_id == "S1"
    complete = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_complete")
    assert complete.selected_provider == "gemini"
    assert complete.provider == "gemini" and complete.model == "gemini-test"
    assert complete.retry_count == 1 and complete.elapsed_ms == 700
    assert complete.output_tokens == 2120
    assert not hasattr(complete, "prompt") and not hasattr(complete, "essay")


def test_ship30_continuation_uses_validated_word_count_not_uncited_raw_length(caplog):
    caplog.set_level("INFO")
    from app.agents.providers import GenerationResult
    from app.rag.retrieval import Passage
    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)
    class FakeRetriever:
        def retrieve(self, _query): return [passage]
    uncited = "This claim has no retrieved evidence or source citation."
    cited = "Track D7 retention to understand continued use. [S1]"
    class SequenceGemini:
        provider_name, model_name = "gemini", "gemini-test"
        def __init__(self): self.prompts = []
        def generate_with_metadata(self, _system, prompt):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                # Raw word count exceeds target, but strict citation validation
                # discards almost all of the response.
                return GenerationResult("# Retention\n\n" + " ".join([uncited] * 30) + "\n\n" + cited, "gemini", "gemini-test", 50, 2800, False, "STOP")
            return GenerationResult(" ".join([cited] * 20), "gemini", "gemini-test", 80, 900, False, "STOP")
    llm = SequenceGemini()
    service = RAGService(
        FakeRetriever(), llm, preserve_markdown_structure=True, compact_context=True,
        minimum_response_words=100, target_response_words=100, max_continuations=1,
    )

    answer = service.answer("Write a cited retention essay.", system_prompt="Use only the evidence.")

    assert answer.grounded is True
    assert len(llm.prompts) == 2
    assert "Current citation-validated essay draft" in llm.prompts[1]
    assert uncited not in llm.prompts[1]
    assert answer.answer.count("[S1]") == 21
    assert "no retrieved evidence" not in answer.answer
    attempt_records = [record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_attempt_complete"]
    assert len(attempt_records) == 2
    assert attempt_records[0].finish_reason == "STOP"
    assert attempt_records[0].output_tokens == 2800
    assert attempt_records[0].raw_word_count > 100
    complete = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_complete")
    assert complete.first_response_word_count > 100
    assert complete.final_word_count >= 100
    assert complete.retry_count == 1


def test_ship30_continuation_provider_failure_is_bounded_and_not_validation_failure(caplog):
    from app.agents.providers import GenerationResult, GeminiTimeoutError
    from app.rag.retrieval import Passage
    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)
    class FakeRetriever:
        def retrieve(self, _query): return [passage]
    class FailsDuringContinuation:
        provider_name, model_name = "gemini", "gemini-test"
        def __init__(self): self.calls = 0
        def generate_with_metadata(self, *_args):
            self.calls += 1
            if self.calls == 1:
                return GenerationResult("# Retention\n\nTrack D7 retention helps explain continued use. [S1]", "gemini", "gemini-test", 20, 30, False, "STOP")
            raise GeminiTimeoutError("Gemini request timed out safely.")
    llm = FailsDuringContinuation()
    service = RAGService(FakeRetriever(), llm, preserve_markdown_structure=True, minimum_response_words=100, target_response_words=100, max_continuations=1)

    with pytest.raises(GeminiTimeoutError, match="timed out safely"):
        service.answer("Write a cited retention essay.", system_prompt="Cite claims.")

    assert llm.calls == 2
    failed = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_failed")
    assert failed.failure_category == "provider_error" and failed.retry_count == 1
    assert not any(getattr(record, "event", None) == "ship30_validation_failed" for record in caplog.records)


def test_ship30_continuation_is_bounded_and_short_essay_is_rejected():
    from app.agents.providers import GenerationResult
    from app.rag.retrieval import Passage
    from app.services.rag import IncompleteEssayError
    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)
    class FakeRetriever:
        def retrieve(self, _query): return [passage]
    class ShortGemini:
        provider_name, model_name = "gemini", "gemini-test"
        def __init__(self): self.calls = 0
        def generate_with_metadata(self, *_args):
            self.calls += 1
            return GenerationResult("# Retention\n\nTeams track retention. [S1]", "gemini", "gemini-test", 5, 8, False)
    llm = ShortGemini()
    service = RAGService(
        FakeRetriever(), llm, preserve_markdown_structure=True,
        minimum_response_words=100, target_response_words=200, max_continuations=5,
    )
    with pytest.raises(IncompleteEssayError) as failure:
        service.answer("Write a retention essay.", system_prompt="Cite claims.")
    assert failure.value.category == "insufficient_word_count"
    assert llm.calls == 3


def test_ship30_provider_failure_is_not_reported_as_essay_validation_failure(caplog):
    from app.agents.providers import GeminiQuotaError
    from app.rag.retrieval import Passage
    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)
    class FakeRetriever:
        def retrieve(self, _query): return [passage]
    class FailedGemini:
        provider_name, model_name = "gemini", "gemini-test"
        def generate(self, *_args): raise GeminiQuotaError("Gemini quota or rate limit was reached.")
    service = RAGService(FakeRetriever(), FailedGemini(), minimum_response_words=1000)
    with pytest.raises(GeminiQuotaError, match="quota or rate limit"):
        service.answer("Write about retention.", system_prompt="Cite claims.")
    failed = next(record for record in caplog.records if getattr(record, "event", None) == "ship30_generation_failed")
    assert failed.failure_category == "provider_error"
    assert failed.provider == "gemini" and failed.model == "gemini-test"


def test_ship30_single_call_timeout_raises_without_retry():
    from app.agents.providers import OllamaTimeoutError
    from app.rag.retrieval import Passage

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class TimedOutLLM:
        def __init__(self): self.calls = 0
        def generate(self, *_args):
            self.calls += 1
            raise OllamaTimeoutError("Ollama did not respond within 180 seconds.")

    llm = TimedOutLLM()
    service = RAGService(FakeRetriever(), llm, preserve_markdown_structure=True, compact_context=True)
    with pytest.raises(OllamaTimeoutError, match="did not respond"):
        service.answer(
            "Write a retention essay.", retrieval_query="retention",
            system_prompt="Cite claims.",
        )
    assert llm.calls == 1


def test_ship30_missing_citations_are_not_retried_or_accepted():
    from app.rag.retrieval import Passage

    passage = Passage("Track D7 retention to understand continued use.", {
        "source_path": "podcasts/retention.md", "chunk_id": "retention-1", "title": "Retention", "document_type": "podcast",
    }, .9)

    class FakeRetriever:
        def retrieve(self, _query): return [passage]

    class NoCitationLLM:
        def __init__(self): self.prompts = []
        def generate(self, _system, prompt):
            self.prompts.append(prompt)
            return "# Retention without proof\n\nTeams will definitely succeed."

    llm = NoCitationLLM()
    service = RAGService(FakeRetriever(), llm, preserve_markdown_structure=True, compact_context=True)
    answer = service.answer("Write about retention.", retrieval_query="retention", system_prompt="Use citations.")

    assert len(llm.prompts) == 1
    assert answer.grounded is False
    assert answer.sources == []
    assert "Available citation labels: [S1]" in llm.prompts[0]


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

