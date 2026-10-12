"""Embedding provider interface and Ollama implementation."""
import os
import shutil
import subprocess
import threading
import time
from typing import Protocol
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from socket import timeout as SocketTimeout
from pathlib import Path
from urllib.parse import urlsplit
import json


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddings:
    _startup_lock = threading.Lock()

    def __init__(self, base_url: str, model: str, timeout: float = 120):
        if timeout <= 0:
            raise ValueError("Embedding timeout must be positive")
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    def _ensure_local_server(self) -> None:
        """Start the installed Ollama server on demand for local desktop setups."""
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return

        def healthy() -> bool:
            try:
                with urlopen(f"{self.base_url}/api/tags", timeout=1):
                    return True
            except (URLError, SocketTimeout, TimeoutError, OSError):
                return False

        if healthy():
            return
        with self._startup_lock:
            if healthy():
                return
            executable = shutil.which("ollama")
            if not executable and os.name == "nt":
                local_app_data = os.environ.get("LOCALAPPDATA")
                installed_cli = Path(local_app_data or "") / "Programs" / "Ollama" / "ollama.exe"
                if installed_cli.is_file():
                    executable = str(installed_cli)
            if not executable:
                raise RuntimeError(
                    f"Ollama is not running at {parsed.hostname}:{parsed.port or 11434}, and its CLI was not found."
                )

            env = os.environ.copy()
            env["OLLAMA_HOST"] = f"{parsed.hostname}:{parsed.port or 11434}"
            options = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "env": env,
            }
            if os.name == "nt":
                options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                options["start_new_session"] = True
            try:
                process = subprocess.Popen([executable, "serve"], **options)
            except OSError as exc:
                raise RuntimeError("Ollama was installed but its local server could not be started.") from exc

            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if healthy():
                    return
                if process.poll() is not None:
                    break
                time.sleep(0.25)
            raise RuntimeError(
                "Ollama's local server did not become ready within 20 seconds. "
                "Check the Ollama installation and configured OLLAMA_BASE_URL."
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_local_server()
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
