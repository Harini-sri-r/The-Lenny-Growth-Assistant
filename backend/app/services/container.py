"""Construct request-scoped RAG dependencies from settings."""
import logging
import os
from pathlib import Path

from app.agents.providers import create_llm_provider
from app.agents.lenny_agent import ClaudeResearchAgent
from app.core.config import get_settings
from app.core.rag_diagnostics import log_rag_diagnostic
from app.rag.embeddings import OllamaEmbeddings
from app.rag.retrieval import Retriever
from app.rag.vector_store import ChromaVectorStore
from app.services.rag import RAGService

logger = logging.getLogger(__name__)


def get_retriever() -> Retriever:
    settings = get_settings()
    try:
        store = ChromaVectorStore(str(settings.chroma_persist_directory), settings.rag_collection_name)
        embedder = OllamaEmbeddings(settings.ollama_base_url, settings.ollama_embedding_model, settings.llm_timeout_seconds)
        retriever = Retriever(store, embedder, top_k=settings.retrieval_top_k, min_similarity=settings.retrieval_min_similarity)
        if settings.rag_diagnostics:
            log_rag_diagnostic(
                logger, "rag_runtime_config", cwd=os.getcwd(),
                chroma_path=str(Path(settings.chroma_persist_directory).resolve()),
                collection=settings.rag_collection_name, record_count=store.record_count(),
                agent_framework=settings.agent_framework.strip().lower(),
                llm_provider=settings.llm_provider.strip().lower(),
                embedding_model=settings.ollama_embedding_model,
                top_k=settings.retrieval_top_k,
                similarity_threshold=settings.retrieval_min_similarity,
                retriever_id=id(retriever),
            )
        return retriever
    except Exception as exc:
        log_rag_diagnostic(logger, "rag_storage_initialization_failed", error_type=type(exc).__name__)
        raise RuntimeError("RAG storage is unavailable; check ChromaDB installation and local storage") from exc


def get_rag_service():
    settings = get_settings()
    framework = settings.agent_framework.strip().lower()
    llm_model = (
        settings.claude_agent_model if framework == "claude_agent_sdk"
        else settings.ollama_model if settings.llm_provider.strip().lower() == "ollama"
        else settings.openai_model
    )
    log_rag_diagnostic(
        logger, "chat_agent_route", agent_framework=framework,
        llm_provider=settings.llm_provider.strip().lower(), llm_model=llm_model,
    )
    if framework == "claude_agent_sdk":
        try:
            retriever = get_retriever()
            return ClaudeResearchAgent(retriever, model=settings.claude_agent_model, max_turns=settings.claude_agent_max_turns)
        except Exception as exc:
            logger.exception("Could not initialize chat research agent")
            raise RuntimeError("Could not initialize the configured chat research agent") from exc
    if framework == "rag_service":
        try:
            retriever = get_retriever()
            return RAGService(retriever, create_llm_provider(settings))
        except Exception as exc:
            logger.exception("Could not initialize RAG chat service")
            raise RuntimeError("LLM provider configuration is unavailable; check configured provider settings") from exc
    else:
        raise RuntimeError("Unsupported AGENT_FRAMEWORK configuration")


def get_claude_research_agent() -> ClaudeResearchAgent:
    settings = get_settings()
    return ClaudeResearchAgent(get_retriever(), model=settings.claude_agent_model, max_turns=settings.claude_agent_max_turns)
