import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import providers


def test_ollama_chat_bounds_local_answer_generation(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout, headers=None):
        captured.update(url=url, payload=payload, timeout=timeout, headers=headers)
        return {"message": {"content": "A concise grounded response. [S1]"}}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = providers.OllamaProvider("http://localhost:11434", "llama3:latest", timeout=90).generate("system", "question with evidence")

    assert result == "A concise grounded response. [S1]"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["timeout"] == 90
    assert captured["payload"]["options"]["num_predict"] == providers.OllamaProvider.MAX_RESPONSE_TOKENS
    assert captured["payload"]["options"]["num_predict"] == 256


def test_ollama_chat_rejects_malformed_provider_response(monkeypatch):
    monkeypatch.setattr(providers, "_post_json", lambda *_args, **_kwargs: {"response": "unexpected"})
    try:
        providers.OllamaProvider("http://localhost:11434", "llama3:latest").generate("system", "question")
    except RuntimeError as exc:
        assert "unexpected response" in str(exc)
    else:
        raise AssertionError("malformed Ollama response should fail clearly")


def test_ship30_ollama_adapter_rejects_output_truncated_by_token_limit(monkeypatch):
    monkeypatch.setattr(providers, "_post_json", lambda *_args, **_kwargs: {
        "message": {"content": "# Partial essay\n\nA partial cited claim. [S1]"},
        "done_reason": "length",
    })

    with pytest.raises(providers.OllamaTruncatedResponseError, match="output token limit"):
        providers.OllamaProvider(
            "http://localhost:11434", "llama3:latest", max_response_tokens=360,
            reject_truncated=True,
        ).generate("system", "prompt")


def test_normal_chat_adapter_can_parse_token_limited_response(monkeypatch):
    monkeypatch.setattr(providers, "_post_json", lambda *_args, **_kwargs: {
        "message": {"content": "A concise answer."}, "done_reason": "length",
    })

    assert providers.OllamaProvider("http://localhost:11434", "llama3:latest").generate("system", "prompt") == "A concise answer."


def test_ollama_generation_timeout_is_configurable_from_environment(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("OLLAMA_GENERATION_TIMEOUT_SECONDS", "300")
    settings = Settings(_env_file=None)
    provider = providers.create_llm_provider(settings)

    assert settings.ollama_generation_timeout_seconds == 300
    assert provider.timeout == 300


def test_ollama_generation_timeout_has_slow_cpu_default():
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    provider = providers.create_llm_provider(settings)

    assert settings.ollama_generation_timeout_seconds == 240
    assert provider.timeout == 240


def test_ollama_timeout_error_names_configured_limit(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("socket timed out")

    monkeypatch.setattr(providers, "urlopen", timeout)
    try:
        providers.OllamaProvider("http://localhost:11434", "llama3:latest", timeout=240).generate("system", "question")
    except providers.OllamaTimeoutError as exc:
        assert "within 240 seconds" in str(exc)
    else:
        raise AssertionError("Ollama timeout should remain a clear failure")


def test_ollama_connection_failure_has_safe_local_setup_message(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(providers, "urlopen", unavailable)
    with pytest.raises(providers.OllamaUnavailableError, match="Start Ollama and confirm llama3:latest is installed"):
        providers.OllamaProvider("http://localhost:11434", "llama3:latest").generate("system", "private prompt")




def test_openai_provider_selection_falls_back_to_ollama_without_credentials():
    from app.core.config import Settings

    settings = Settings(_env_file=None, llm_provider="openai", openai_api_key="")
    provider = providers.create_llm_provider(settings)

    assert isinstance(provider, providers.OllamaProvider)


def test_openai_provider_failure_falls_back_to_ollama_without_logging_error_text(monkeypatch, caplog):
    from app.core.config import Settings

    private_error = "private cloud failure fake-secret"
    calls = []

    def fake_post(url, payload, timeout, headers=None):
        calls.append(url)
        if "api.openai.com" in url:
            raise RuntimeError(private_error)
        return {"message": {"content": "Grounded local answer. [S1]"}}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    settings = Settings(_env_file=None, llm_provider="openai", openai_api_key="test-only-cloud-key")
    provider = providers.create_llm_provider(settings)
    result = provider.generate("system", "question with evidence")

    assert isinstance(provider, providers.OllamaFallbackProvider)
    assert result == "Grounded local answer. [S1]"
    assert calls == ["https://api.openai.com/v1/chat/completions", "http://127.0.0.1:11434/api/chat"]
    assert private_error not in caplog.text
    assert "test-only-cloud-key" not in caplog.text


def test_openai_fallback_preserves_safe_ollama_timeout_type():
    class FailedCloud:
        def generate(self, *_args): raise RuntimeError("private cloud failure")

    class TimedOutOllama:
        def generate(self, *_args): raise providers.OllamaTimeoutError("Ollama timed out safely")

    provider = providers.OllamaFallbackProvider(FailedCloud(), TimedOutOllama())
    with pytest.raises(providers.OllamaTimeoutError, match="timed out safely"):
        provider.generate("system", "prompt")


def test_gemini_provider_uses_sdk_configuration_and_returns_text(monkeypatch):
    import sys
    from types import SimpleNamespace

    seen = {}
    class FakeTypes:
        class GenerateContentConfig:
            def __init__(self, **kwargs): self.kwargs = kwargs
    class Models:
        def generate_content(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(text="Grounded Gemini response. [S1]")
    fake_google_genai = SimpleNamespace(types=FakeTypes)
    monkeypatch.setitem(sys.modules, "google.genai", fake_google_genai)
    provider = providers.GeminiProvider("test-key", "gemini-test", client=SimpleNamespace(models=Models()))

    assert provider.generate("system grounding", "question and evidence") == "Grounded Gemini response. [S1]"
    assert seen["model"] == "gemini-test"
    assert seen["contents"] == "question and evidence"
    assert seen["config"].kwargs == {"system_instruction": "system grounding", "max_output_tokens": None}


def test_gemini_response_extracts_text_token_usage_and_truncation(monkeypatch):
    import sys
    from types import SimpleNamespace
    class FakeTypes:
        class GenerateContentConfig:
            def __init__(self, **kwargs): self.kwargs = kwargs
    monkeypatch.setitem(sys.modules, "google.genai", SimpleNamespace(types=FakeTypes))
    response = SimpleNamespace(
        text="A partial essay. [S1]",
        candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
        usage_metadata=SimpleNamespace(candidates_token_count=2800, prompt_token_count=350, total_token_count=3150),
    )
    class Models:
        def generate_content(self, **kwargs):
            assert kwargs["config"].kwargs["max_output_tokens"] == 3000
            return response
    provider = providers.GeminiProvider("fake-key", "gemini-test", client=SimpleNamespace(models=Models()), max_output_tokens=3000)
    result = provider.generate_with_metadata("system", "prompt")
    assert result.text == "A partial essay. [S1]"
    assert result.provider == "gemini" and result.model == "gemini-test"
    assert result.output_tokens == 2800 and result.truncated is True
    assert result.finish_reason == "MAX_TOKENS"
    assert result.input_tokens == 350 and result.total_tokens == 3150
    assert result.configured_output_token_limit == 3000


def test_gemini_sdk_client_receives_key_timeout_and_single_attempt(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace
    seen = {}
    class HttpOptions:
        def __init__(self, **kwargs): self.kwargs = kwargs
    class HttpRetryOptions:
        def __init__(self, **kwargs): self.kwargs = kwargs
    def create_client(**kwargs):
        seen.update(kwargs)
        return object()
    types_module = SimpleNamespace(HttpOptions=HttpOptions, HttpRetryOptions=HttpRetryOptions)
    genai_module = SimpleNamespace(Client=create_client)
    google_module = ModuleType("google")
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", SimpleNamespace(types=types_module))

    providers.GeminiProvider("fake-key", "gemini-test", 12.5)

    assert seen["api_key"] == "fake-key"
    assert seen["http_options"].kwargs["timeout"] == 12500
    assert seen["http_options"].kwargs["retry_options"].kwargs == {"attempts": 1}


def test_gemini_provider_classifies_quota_timeout_without_provider_text_or_key(monkeypatch, caplog):
    import sys
    from types import SimpleNamespace
    class FakeTypes:
        class GenerateContentConfig:
            def __init__(self, **_kwargs): pass
    monkeypatch.setitem(sys.modules, "google.genai", SimpleNamespace(types=FakeTypes))
    class ResourceExhausted(Exception):
        code = 429
    secret_text = "provider response contains private data and fake-secret"
    class Models:
        def generate_content(self, **_kwargs): raise ResourceExhausted(secret_text)
    provider = providers.GeminiProvider("fake-api-key", "gemini-test", client=SimpleNamespace(models=Models()))

    with pytest.raises(providers.GeminiQuotaError, match="quota or rate limit"):
        provider.generate("private prompt", "private evidence")
    assert secret_text not in caplog.text
    assert "fake-api-key" not in caplog.text

    assert isinstance(providers._classify_gemini_error(TimeoutError("private timeout detail")), providers.GeminiTimeoutError)
    assert "private timeout detail" not in str(providers._classify_gemini_error(TimeoutError("private timeout detail")))


def test_gemini_selection_missing_key_uses_ollama_without_importing_sdk():
    from app.core.config import Settings
    settings = Settings(_env_file=None, llm_provider="gemini", gemini_api_key="")
    provider = providers.create_llm_provider(settings)
    assert isinstance(provider, providers.OllamaProvider)


def test_ship30_ollama_selection_keeps_local_provider_and_large_configured_budget():
    from app.core.config import Settings
    settings = Settings(_env_file=None, llm_provider="ollama")
    selected = providers.create_llm_provider(
        settings, max_response_tokens=settings.ship30_max_output_tokens,
        ollama_timeout=settings.ship30_generation_timeout_seconds,
        ollama_reject_truncated=False, fallback=False,
    )
    assert isinstance(selected, providers.OllamaProvider)
    assert selected.provider_name == "ollama"
    assert selected.model_name == "llama3:latest"
    assert selected.max_response_tokens == 3000 and selected.timeout == 180


def test_gemini_selection_with_key_uses_cloud_then_falls_back(monkeypatch, caplog):
    from app.core.config import Settings
    class FakeGemini:
        def __init__(self, api_key, model, timeout, **_kwargs):
            assert (api_key, model, timeout) == ("test-key", "gemini-test", 90)
        def generate(self, *_args): raise providers.GeminiQuotaError("quota safe")
    class FakeOllama:
        def generate(self, *_args): return "Fallback answer. [S1]"
    monkeypatch.setattr(providers, "GeminiProvider", FakeGemini)
    monkeypatch.setattr(providers, "create_ollama_provider", lambda *_args, **_kwargs: FakeOllama())
    settings = Settings(_env_file=None, llm_provider="gemini", gemini_api_key="test-key", gemini_model="gemini-test")
    result = providers.create_llm_provider(settings).generate("system", "prompt")
    assert result == "Fallback answer. [S1]"
    assert "quota safe" not in caplog.text


def test_ship30_gemini_selection_is_direct_bounded_and_configured(monkeypatch):
    from app.core.config import Settings
    settings = Settings(_env_file=None, llm_provider="gemini", gemini_api_key="test-key", gemini_model="gemini-test")
    made = {}
    class FakeGemini:
        def __init__(self, api_key, model, timeout, **kwargs):
            made.update(api_key=api_key, model=model, timeout=timeout, kwargs=kwargs)
            self.provider_name, self.model_name = "gemini", model
    monkeypatch.setattr(providers, "GeminiProvider", FakeGemini)
    selected = providers.create_llm_provider(
        settings, max_response_tokens=3000, provider_timeout=180, fallback=False,
    )
    assert isinstance(selected, FakeGemini)
    assert made == {"api_key": "test-key", "model": "gemini-test", "timeout": 180,
                    "kwargs": {"max_output_tokens": 3000}}


def test_ship30_gemini_missing_key_is_actionable_instead_of_silent_ollama_fallback():
    from app.core.config import Settings
    selected = providers.create_llm_provider(
        Settings(_env_file=None, llm_provider="gemini", gemini_api_key=""), fallback=False,
    )
    assert selected.provider_name == "gemini"
    with pytest.raises(providers.ProviderConfigurationError, match="GEMINI_API_KEY is required"):
        selected.generate("system", "prompt")


def test_gemini_provider_rejects_missing_credentials():
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        providers.GeminiProvider("", "gemini-test")
