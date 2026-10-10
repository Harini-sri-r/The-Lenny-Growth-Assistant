"""LLM provider interface and independently selectable Ollama/OpenAI adapters."""
from typing import Protocol
from urllib.request import Request, urlopen
import json


class LLMProvider(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class OllamaProvider:
    # Keep interactive answers bounded so local inference doesn't spend the
    # request timeout generating an unnecessarily long response.
    MAX_RESPONSE_TOKENS = 96

    def __init__(self, base_url: str, model: str, timeout: float = 90):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"num_predict": self.MAX_RESPONSE_TOKENS},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        response = _post_json(f"{self.base_url}/api/chat", payload, self.timeout)
        try:
            return response["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Ollama chat returned an unexpected response") from exc


class OpenAIProvider:
    """OpenAI-compatible cloud chat adapter; requires an explicitly configured API key."""
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: float = 90):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai provider")
        self.api_key, self.model, self.timeout = api_key, model, timeout

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = _post_json("https://api.openai.com/v1/chat/completions", {"model": self.model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]}, self.timeout, {"Authorization": f"Bearer {self.api_key}"})
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Cloud LLM returned an unexpected response") from exc


def create_llm_provider(settings) -> LLMProvider:
    """Construct the explicitly selected provider from application settings."""
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.llm_timeout_seconds)
    if provider == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.llm_timeout_seconds)
    raise ValueError(f"Unsupported LLM_PROVIDER {settings.llm_provider!r}; choose 'ollama' or 'openai'")


def _post_json(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=json.dumps(payload).encode(), headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except Exception as exc:
        raise RuntimeError(f"LLM provider request failed: {exc}") from exc
