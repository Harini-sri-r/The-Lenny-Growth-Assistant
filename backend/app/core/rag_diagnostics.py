"""Content-free diagnostics and correlation for tracing a RAG request."""
from contextvars import ContextVar
import logging

from app.core.config import get_settings


request_id_context: ContextVar[str | None] = ContextVar("rag_request_id", default=None)


def log_rag_diagnostic(logger: logging.Logger, event: str, **fields) -> None:
    if not get_settings().rag_diagnostics:
        return
    request_id = request_id_context.get()
    extra = {"event": event, **fields}
    if request_id:
        extra["request_id"] = request_id
    logger.info(event, extra=extra)


def log_rag_failure(logger: logging.Logger, message: str, *, stage: str, exc: Exception, stage_elapsed_ms: float | None = None) -> None:
    """Always log a failed RAG stage; successful progress events remain opt-in."""
    extra = {"event": "rag_stage_failed", "stage": stage, "error_type": type(exc).__name__}
    request_id = request_id_context.get()
    if request_id:
        extra["request_id"] = request_id
    if stage_elapsed_ms is not None:
        extra["stage_elapsed_ms"] = stage_elapsed_ms
    logger.exception(message, extra=extra)


def request_context(request_id: str | None):
    """Temporarily correlate synchronous work with the request middleware ID."""
    return request_id_context.set(request_id) if request_id else None
