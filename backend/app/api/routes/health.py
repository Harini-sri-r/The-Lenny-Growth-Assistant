"""Liveness endpoints; these do not require external services."""
from fastapi import APIRouter
from app.core.config import get_settings

router = APIRouter()


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/providers", tags=["health"])
def provider_status() -> dict:
    """Expose safe provider configuration without probing providers or returning secrets."""
    settings = get_settings()
    framework = settings.agent_framework.strip().lower()
    configured_provider = settings.llm_provider.strip().lower()
    anthropic_configured = bool(settings.anthropic_api_key.strip())
    openai_configured = bool(settings.openai_api_key.strip())
    gemini_configured = bool(settings.gemini_api_key.strip())

    if framework == "pi_coding_agent":
        if configured_provider == "gemini" and gemini_configured:
            route = "pi_gemini"
        elif configured_provider == "ollama":
            route = "pi_ollama"
        else:
            route = "pi_provider_unavailable"
    elif framework == "claude_agent_sdk":
        route = "anthropic_with_ollama_fallback" if anthropic_configured else "ollama_missing_anthropic_credentials"
    elif framework == "rag_service" and configured_provider == "openai" and openai_configured:
        route = "openai_with_ollama_fallback"
    elif framework == "rag_service" and configured_provider == "gemini" and gemini_configured:
        route = "gemini_with_ollama_fallback"
    elif framework == "rag_service" and configured_provider == "gemini":
        route = "ollama_missing_gemini_credentials"
    else:
        route = "ollama"

    return {
        "configured_route": route,
        "route_label": {
            "pi_gemini": f"Pi Coding Agent with Gemini ({settings.gemini_model})",
            "pi_ollama": f"Pi Coding Agent with Ollama ({settings.ollama_model})",
            "pi_provider_unavailable": "Pi Coding Agent selected; configure Gemini credentials or select Ollama",
            "anthropic_with_ollama_fallback": "Anthropic Agent SDK with Ollama fallback",
            "ollama_missing_anthropic_credentials": "Ollama (Anthropic credentials not configured)",
            "openai_with_ollama_fallback": "OpenAI for Ship 30; chat falls back to Ollama",
            "gemini_with_ollama_fallback": "Gemini for Ship 30; chat falls back to Ollama",
            "ollama_missing_gemini_credentials": "Ollama for chat; Ship 30 requires Gemini credentials",
            "ollama": "Ollama local provider",
        }[route],
        "providers": [
            {"id": "ollama", "label": "Ollama", "supported": True, "state": "selected" if route in {"ollama", "pi_ollama"} else "fallback", "model": settings.ollama_model},
            {"id": "anthropic", "label": "Anthropic", "supported": True, "state": "selected" if route == "anthropic_with_ollama_fallback" else "credentials_missing" if not anthropic_configured else "optional", "model": settings.claude_agent_model},
            {"id": "gemini", "label": "Gemini", "supported": True, "state": "selected" if route in {"gemini_with_ollama_fallback", "pi_gemini"} else "fallback" if route == "ollama_missing_gemini_credentials" else "credentials_missing" if not gemini_configured else "optional", "model": settings.gemini_model},
            {"id": "openai", "label": "OpenAI", "supported": True, "state": "selected" if route == "openai_with_ollama_fallback" else "credentials_missing" if not openai_configured else "optional", "model": settings.openai_model},
        ],
        "note": "Configuration only; connectivity is not verified. Pi uses the selected provider directly. In rag_service, Ship 30 uses its selected provider directly; regular cloud chat may fall back to Ollama.",
    }
