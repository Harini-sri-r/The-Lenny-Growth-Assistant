"""Embedding provider interface and Ollama implementation."""
from typing import Protocol
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from socket import timeout as SocketTimeout
import json


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddings:
    def __init__(self, base_url: str, model: str, timeout: float = 120):
        if timeout <= 0:
            raise ValueError("Embedding timeout must be positive")
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        request = Request(
            f"{self.base_url}/api/embed",
            data=json.dumps({"model": self.model, "input": texts}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except HTTPError as exc:
            # Do not include an upstream response body: providers may echo input text.
            raise RuntimeError(f"Ollama embedding request failed with HTTP {exc.code} for model {self.model}") from exc
        except (URLError, SocketTimeout, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Ollama embedding request failed for model {self.model} at {self.base_url}: {exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Ollama returned invalid JSON for model {self.model}") from exc
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("Ollama returned an unexpected embedding response")
        return vectors
