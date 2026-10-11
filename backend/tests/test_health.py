import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_versioned_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_provider_status_is_secret_free_and_does_not_claim_provider_connectivity(monkeypatch):
    from app.api.routes import health as route
    from app.core.config import Settings

    monkeypatch.setattr(route, "get_settings", lambda: Settings(
        _env_file=None, agent_framework="claude_agent_sdk", llm_provider="ollama",
        anthropic_api_key="test-only-secret",
    ))
    response = client.get("/api/v1/providers")

    assert response.status_code == 200
    result = response.json()
    assert result["configured_route"] == "anthropic_with_ollama_fallback"
    assert "connectivity" in result["note"]
    assert "test-only-secret" not in response.text
    providers = {provider["id"]: provider for provider in result["providers"]}
    assert providers["anthropic"]["state"] == "selected"
    assert providers["ollama"]["state"] == "fallback"
    assert providers["gemini"]["supported"] is True
    assert providers["gemini"]["state"] == "credentials_missing"


def test_provider_status_reports_gemini_selected_without_credentials(monkeypatch):
    from app.api.routes import health as route
    from app.core.config import Settings
    monkeypatch.setattr(route, "get_settings", lambda: Settings(_env_file=None, llm_provider="gemini", gemini_api_key="", gemini_model="gemini-test"))
    result = client.get("/api/v1/providers").json()
    gemini = next(provider for provider in result["providers"] if provider["id"] == "gemini")
    assert result["configured_route"] == "ollama_missing_gemini_credentials"
    assert gemini == {"id": "gemini", "label": "Gemini", "supported": True, "state": "fallback", "model": "gemini-test"}


def test_provider_status_reports_gemini_cloud_route_without_connectivity_claim(monkeypatch):
    from app.api.routes import health as route
    from app.core.config import Settings
    monkeypatch.setattr(route, "get_settings", lambda: Settings(_env_file=None, llm_provider="gemini", gemini_api_key="test-only-secret", gemini_model="gemini-test"))
    response = client.get("/api/v1/providers")
    result = response.json()
    gemini = next(provider for provider in result["providers"] if provider["id"] == "gemini")
    assert result["configured_route"] == "gemini_with_ollama_fallback"
    assert gemini["state"] == "selected"
    assert "test-only-secret" not in response.text
    assert "connectivity" in result["note"]
