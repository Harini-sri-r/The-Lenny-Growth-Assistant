"""Environment-based application settings."""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    llm_provider: str = "ollama"
    # Claude Agent SDK is the required agent path; RAG remains selectable for
    # the local Ollama demo and for environments without Claude credentials.
    agent_framework: str = "claude_agent_sdk"
    claude_agent_model: str = "sonnet"
    claude_agent_max_turns: int = 5
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @field_validator("transcripts_path", "chroma_persist_directory", mode="before")
    @classmethod
    def resolve_project_paths(cls, value):
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def effective_database_url(self) -> str:
        """Use a safe default DB name/user when DATABASE_URL is unset."""
        import os
        return os.environ.get("DATABASE_URL") or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
