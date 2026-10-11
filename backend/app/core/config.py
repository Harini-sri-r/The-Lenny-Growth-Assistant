"""Environment-based application settings."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
