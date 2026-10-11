"""LLM provider interface and independently selectable Ollama/OpenAI adapters."""
import logging
from typing import Protocol
from urllib.request import Request, urlopen
import json
from dataclasses import dataclass
from time import perf_counter

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


@dataclass(frozen=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    elapsed_ms: float
    output_tokens: int | None = None
    truncated: bool = False
    finish_reason: str | None = None
    input_tokens: int | None = None
    total_tokens: int | None = None
    configured_output_token_limit: int | None = None


def _finish_reason_name(value) -> str:
    if value is None:
        return ""
    return str(getattr(value, "name", value)).split(".")[-1].upper()


class OllamaProvider:
    # Leave room for a strategy and its evidence-based explanation while
    # keeping local interactive generation bounded.
    MAX_RESPONSE_TOKENS = 256

    def __init__(
        self, base_url: str, model: str, timeout: float = 240, *,
        max_response_tokens: int | None = None, reject_truncated: bool = False,
    ):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.provider_name, self.model_name = "ollama", model
        self.max_response_tokens = max_response_tokens or self.MAX_RESPONSE_TOKENS
        self.reject_truncated = reject_truncated

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self.generate_with_metadata(system_prompt, user_prompt).text

    def generate_with_metadata(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        started = perf_counter()
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"num_predict": self.max_response_tokens},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = _post_json(f"{self.base_url}/api/chat", payload, self.timeout)
        except RuntimeError as exc:
            message = str(exc).lower()
            if "timed out" in message or "timeout" in message:
                raise OllamaTimeoutError(
                    f"Ollama did not respond within {self.timeout:g} seconds. Check the local model or timeout setting."
                ) from None
            if any(marker in message for marker in (
                "urlopen error", "connection refused", "actively refused", "failed to establish",
                "no route to host", "name or service not known", "temporary failure in name resolution",
            )):
                raise OllamaUnavailableError(
                    f"Ollama is unavailable. Start Ollama and confirm {self.model} is installed."
                ) from None
            raise OllamaGenerationError(
                "Ollama could not complete generation. Check the local model and Ollama server."
            ) from None
        try:
            if self.reject_truncated and response.get("done_reason") == "length":
                raise OllamaTruncatedResponseError()
            text = response["message"]["content"]
            output_tokens = response.get("eval_count")
            return GenerationResult(
                text=text, provider=self.provider_name, model=self.model_name,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
                truncated=response.get("done_reason") == "length",
                input_tokens=response.get("prompt_eval_count") if isinstance(response.get("prompt_eval_count"), int) else None,
                total_tokens=(response.get("prompt_eval_count", 0) + output_tokens
                              if isinstance(response.get("prompt_eval_count"), int) and isinstance(output_tokens, int) else None),
                configured_output_token_limit=self.max_response_tokens,
            )
        except OllamaGenerationError:
            raise
        except (KeyError, TypeError) as exc:
            raise OllamaGenerationError("Ollama returned an unexpected response. Check the local model and Ollama server.") from exc


class OllamaUnavailableError(RuntimeError):
    """The local Ollama service could not be reached."""


class OllamaTimeoutError(RuntimeError):
    """The local Ollama generation request exceeded its configured timeout."""


class OllamaGenerationError(RuntimeError):
    """Ollama was reachable but could not produce a usable response."""


class OllamaTruncatedResponseError(OllamaGenerationError):
    """Ollama stopped at its output limit before completing a Ship 30 essay."""

    def __init__(self):
        super().__init__("Ollama reached the output token limit before completing the Ship 30 essay; no artifact was saved.")


class OpenAIProvider:
    """OpenAI-compatible cloud chat adapter; requires an explicitly configured API key."""
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: float = 90):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai provider")
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.provider_name, self.model_name = "openai", model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = _post_json("https://api.openai.com/v1/chat/completions", {"model": self.model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]}, self.timeout, {"Authorization": f"Bearer {self.api_key}"})
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Cloud LLM returned an unexpected response") from exc


class GeminiProvider:
    """Google Gemini adapter using the official google-genai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash", timeout: float = 90, *, client=None, max_output_tokens: int | None = None):
        if not api_key.strip():
            raise ValueError("GEMINI_API_KEY is required for the gemini provider")
        self.model, self.timeout = model, timeout
        self.provider_name, self.model_name = "gemini", model
        self.max_output_tokens = max_output_tokens
        if client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise RuntimeError("Gemini provider requires google-genai; install backend requirements") from exc
            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(
                        timeout=int(timeout * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
            except Exception:
                raise GeminiGenerationError("Gemini client could not be initialized; check SDK and credential configuration.") from None
        self.client = client

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self.generate_with_metadata(system_prompt, user_prompt).text

    def generate_with_metadata(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        started = perf_counter()
        try:
            from google.genai import types
            response = self.client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.max_output_tokens,
                ),
            )
            text = response.text
            if not isinstance(text, str) or not text.strip():
                raise GeminiGenerationError("Gemini returned an empty response.")
            candidates = getattr(response, "candidates", None) or []
            finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
            usage = getattr(response, "usage_metadata", None)
            output_tokens = getattr(usage, "candidates_token_count", None) if usage is not None else None
            input_tokens = getattr(usage, "prompt_token_count", None) if usage is not None else None
            total_tokens = getattr(usage, "total_token_count", None) if usage is not None else None
            return GenerationResult(
                text=text, provider=self.provider_name, model=self.model_name,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
                truncated=_finish_reason_name(finish_reason) in {"MAX_TOKENS", "LENGTH"},
                finish_reason=_finish_reason_name(finish_reason) or None,
                input_tokens=input_tokens if isinstance(input_tokens, int) else None,
                total_tokens=total_tokens if isinstance(total_tokens, int) else None,
                configured_output_token_limit=self.max_output_tokens,
            )
        except GeminiGenerationError:
            raise
        except Exception as exc:
            raise _classify_gemini_error(exc) from None


class GeminiError(RuntimeError):
    """Safe Gemini provider failure suitable for application handling."""


class GeminiQuotaError(GeminiError):
    pass


class GeminiCredentialsError(GeminiError):
    pass


class GeminiTimeoutError(GeminiError):
    pass


class GeminiGenerationError(GeminiError):
    pass


class ProviderConfigurationError(RuntimeError):
    """Safe error raised when the selected provider is not configured."""


class _ConfigurationErrorProvider:
    def __init__(self, provider: str, model: str, message: str):
        self.provider_name, self.model_name, self.message = provider, model, message

    def generate(self, *_args):
        raise ProviderConfigurationError(self.message)


def _classify_gemini_error(exc: Exception) -> GeminiError:
    """Map SDK errors to safe messages without returning provider text or secrets."""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    name = type(exc).__name__.lower()
    if isinstance(exc, (TimeoutError,)) or "timeout" in name:
        return GeminiTimeoutError("Gemini request timed out; check the configured timeout and network connection.")
    if status == 429 or "resourceexhausted" in name or "quota" in name:
        return GeminiQuotaError("Gemini quota or rate limit was reached; check the Google AI project limits.")
    if status in (401, 403) or "unauthenticated" in name or "permissiondenied" in name:
        return GeminiGenerationError("Gemini authentication or permission was rejected; check API key configuration and project access.")
    if status == 404 or "notfound" in name:
        return GeminiGenerationError("The configured Gemini model is unavailable; check GEMINI_MODEL.")
    return GeminiGenerationError("Gemini could not complete generation; check provider configuration and service availability.")


class OllamaFallbackProvider:
    """Use the selected cloud provider when available, otherwise fall back locally."""

    def __init__(self, cloud: LLMProvider, ollama: OllamaProvider):
        self.cloud, self.ollama = cloud, ollama
        self.provider_name = getattr(cloud, "provider_name", "cloud")
        self.model_name = getattr(cloud, "model_name", "unknown")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return self.generate_with_metadata(system_prompt, user_prompt).text

    def generate_with_metadata(self, system_prompt: str, user_prompt: str) -> GenerationResult:
        try:
            return _generate_with_metadata(self.cloud, system_prompt, user_prompt)
        except Exception as exc:
            logger.warning(
                "cloud_llm_fallback_to_ollama",
                extra={"event": "cloud_llm_fallback_to_ollama", "selected_provider": self.provider_name,
                       "selected_model": self.model_name, "actual_provider": "ollama",
                       "actual_model": getattr(self.ollama, "model_name", "unknown"),
                       "error_type": type(exc).__name__},
            )
            try:
                return _generate_with_metadata(self.ollama, system_prompt, user_prompt)
            except (OllamaUnavailableError, OllamaTimeoutError, OllamaGenerationError):
                raise
            except Exception:
                raise RuntimeError("Ollama fallback request failed") from None


def _generate_with_metadata(provider, system_prompt: str, user_prompt: str) -> GenerationResult:
    started = perf_counter()
    method = getattr(provider, "generate_with_metadata", None)
    if callable(method):
        return method(system_prompt, user_prompt)
    text = provider.generate(system_prompt, user_prompt)
    return GenerationResult(
        text=text, provider=getattr(provider, "provider_name", type(provider).__name__),
        model=getattr(provider, "model_name", "unknown"),
        elapsed_ms=round((perf_counter() - started) * 1000, 2),
    )


def create_ollama_provider(
    settings, *, max_response_tokens: int | None = None, timeout: float | None = None,
    reject_truncated: bool = False,
) -> OllamaProvider:
    return OllamaProvider(
        settings.ollama_base_url, settings.ollama_model,
        timeout if timeout is not None else settings.ollama_generation_timeout_seconds,
        max_response_tokens=max_response_tokens,
        reject_truncated=reject_truncated,
    )


def create_llm_provider(
    settings, *, max_response_tokens: int | None = None, ollama_timeout: float | None = None,
    ollama_reject_truncated: bool = False, provider_timeout: float | None = None,
    fallback: bool = True,
) -> LLMProvider:
    """Construct the explicitly selected provider from application settings."""
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return create_ollama_provider(
            settings, max_response_tokens=max_response_tokens, timeout=ollama_timeout,
            reject_truncated=ollama_reject_truncated,
        )
    if provider == "openai":
        if not fallback and not settings.openai_api_key.strip():
            return _ConfigurationErrorProvider(
                "openai", settings.openai_model,
                "OPENAI_API_KEY is required for Ship 30 when LLM_PROVIDER=openai",
            )
        ollama = create_ollama_provider(
            settings, max_response_tokens=max_response_tokens, timeout=ollama_timeout,
            reject_truncated=ollama_reject_truncated,
        )
        if not settings.openai_api_key.strip():
            logger.info(
                "cloud_llm_credentials_missing_using_ollama",
                extra={"event": "cloud_llm_credentials_missing_using_ollama", "provider": "openai"},
            )
            return ollama
        cloud = OpenAIProvider(settings.openai_api_key, settings.openai_model, provider_timeout or settings.llm_timeout_seconds)
        return OllamaFallbackProvider(cloud, ollama) if fallback else cloud
    if provider == "gemini":
        ollama = create_ollama_provider(
            settings, max_response_tokens=max_response_tokens, timeout=ollama_timeout,
            reject_truncated=ollama_reject_truncated,
        )
        if not settings.gemini_api_key.strip():
            if not fallback:
                return _ConfigurationErrorProvider(
                    "gemini", settings.gemini_model,
                    "GEMINI_API_KEY is required for Ship 30 when LLM_PROVIDER=gemini",
                )
            logger.info(
                "cloud_llm_credentials_missing_using_ollama",
                extra={"event": "cloud_llm_credentials_missing_using_ollama", "provider": "gemini"},
            )
            return ollama
        cloud = GeminiProvider(
            settings.gemini_api_key, settings.gemini_model,
            provider_timeout or settings.llm_timeout_seconds,
            max_output_tokens=max_response_tokens,
        )
        return OllamaFallbackProvider(cloud, ollama) if fallback else cloud
    raise ValueError(f"Unsupported LLM_PROVIDER {settings.llm_provider!r}; choose 'ollama', 'openai', or 'gemini'")


def _post_json(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=json.dumps(payload).encode(), headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            raise RuntimeError(f"LLM provider request timed out after {timeout:g} seconds") from exc
        raise RuntimeError(f"LLM provider request failed: {exc}") from exc
