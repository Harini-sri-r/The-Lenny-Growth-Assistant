import sys
from pathlib import Path

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
    assert captured["payload"]["options"]["num_predict"] == 96


def test_ollama_chat_rejects_malformed_provider_response(monkeypatch):
    monkeypatch.setattr(providers, "_post_json", lambda *_args, **_kwargs: {"response": "unexpected"})
    try:
        providers.OllamaProvider("http://localhost:11434", "llama3:latest").generate("system", "question")
    except RuntimeError as exc:
        assert "unexpected response" in str(exc)
    else:
        raise AssertionError("malformed Ollama response should fail clearly")
