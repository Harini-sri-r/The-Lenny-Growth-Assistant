"""Environment-based application settings."""
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

_source_root = Path(__file__).resolve().parents[3]
PROJECT_ROOT = _source_root if (_source_root / ".env").exists() else Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "Lenny Growth Assistant"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://lenny:example_password@localhost:5432/lenny"
    transcripts_path: Path = Path("./lennys-newsletterpodcastdata-main")
    chroma_persist_directory: Path = Path("./chroma")
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3:latest"
    ollama_embedding_model: str = "nomic-embed-text"
    rag_collection_name: str = "lenny_transcripts"
    chunk_size: int = 1200
    chunk_overlap: int = 180
    embedding_batch_size: int = 8
    retrieval_top_k: int = 5
    retrieval_min_similarity: float = 0.25
    rag_diagnostics: bool = False
    llm_timeout_seconds: float = 90
    ollama_generation_timeout_seconds: float = Field(default=240, gt=0)
    llm_provider: str = "ollama"
    ship30_generation_timeout_seconds: float = Field(default=180, gt=0)
    ship30_max_output_tokens: int = Field(default=3000, gt=0)
    ship30_minimum_response_words: int = Field(default=1150, gt=0)
    ship30_max_continuations: int = Field(default=3, ge=0, le=3)
    # Keep the no-credential local Ollama workflow as the application default.
    agent_framework: str = "rag_service"
    pi_command: str = "pi"
    pi_timeout_seconds: float = Field(default=240, gt=0)
    pi_ship30_timeout_seconds: float = Field(default=900, gt=0)
    claude_agent_model: str = "sonnet"
    claude_agent_max_turns: int = 5
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    auth_cookie_secure: bool = False
    auth_session_days: int = Field(default=7, ge=1, le=30)

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @field_validator("transcripts_path", "chroma_persist_directory", mode="before")
    @classmethod
    def resolve_project_paths(cls, value):
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @field_validator("ollama_base_url", mode="before")
    @classmethod
    def normalize_local_ollama_url(cls, value):
        """Prefer IPv4 loopback because Windows Ollama commonly binds 127.0.0.1 only."""
        if not isinstance(value, str):
            return value
        parsed = urlsplit(value.strip())
        if parsed.hostname and parsed.hostname.lower() == "localhost":
            netloc = re.sub(r"localhost", "127.0.0.1", parsed.netloc, count=1, flags=re.IGNORECASE)
            return parsed._replace(netloc=netloc).geturl()
        return value

    @property
    def effective_database_url(self) -> str:
        """Build a safely escaped container URL from separate database settings."""
        import os
        database_host = os.environ.get("DATABASE_HOST")
        if database_host:
            return URL.create(
                drivername="postgresql+psycopg",
                username=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"],
                host=database_host,
                port=int(os.environ.get("DATABASE_PORT", "5432")),
                database=os.environ["POSTGRES_DB"],
            ).render_as_string(hide_password=False)
        return os.environ.get("DATABASE_URL") or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
