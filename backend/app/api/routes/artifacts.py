"""Grounded Ship 30 for 30 essay generation and persisted artifact listing."""
import re
import logging
from html import unescape
from html.parser import HTMLParser

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.chat import _require_session
from app.agents.providers import (
    GeminiError, GeminiTimeoutError, OllamaGenerationError, OllamaTimeoutError,
    OllamaTruncatedResponseError, OllamaUnavailableError, ProviderConfigurationError,
)
from app.database.session import get_db
from app.models.chat import ChatArtifact
from app.schemas.chat import ArtifactOut, ArtifactRequest
from app.services.container import get_claude_research_agent
from app.services.rag import IncompleteEssayError
from app.agents.lenny_agent import ClaudeResearchAgent, PiAgentTimeoutError, ship30_system_prompt
from app.core.rag_diagnostics import log_rag_diagnostic, request_id_context
from app.core.config import get_settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
logger = logging.getLogger(__name__)


class _HTMLWordCounter(HTMLParser):
    """Count visible HTML text, excluding style and script blocks."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"style", "script"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"style", "script"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def _artifact_word_count(content: str, artifact_format: str) -> int:
    if artifact_format == "html":
        parser = _HTMLWordCounter()
        parser.feed(content)
        content = " ".join(parser.parts)
    else:
        content = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
        content = re.sub(r"`[^`]*`", " ", content)
        content = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", content)
        content = re.sub(r"[#*_>`~]", " ", content)
    return len(re.findall(r"\b[\w'-]+\b", unescape(content)))


@router.post("/ship30", response_model=ArtifactOut, status_code=201)
def generate_ship30(payload: ArtifactRequest, db: Session = Depends(get_db), agent: ClaudeResearchAgent = Depends(get_claude_research_agent)):
    _require_session(db, payload.session_id, payload.user_id)
    format_instruction = "Markdown" if payload.artifact_format == "markdown" else "self-contained HTML with inline CSS and no JavaScript or remote resources"
    prompt = (
        f"Write a Ship 30 for 30 essay about: {payload.topic}\n"
        f"Intended audience: {payload.audience}\nRequested output: {format_instruction}. "
        "Target approximately 1,250 words. Search the transcript knowledge tool before drafting."
    )
    try:
        answer = agent.answer(prompt, system_prompt=ship30_system_prompt(), retrieval_query=payload.topic)
    except OllamaUnavailableError as exc:
        detail = str(exc)
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=503, detail=detail) from None
    except OllamaTimeoutError as exc:
        detail = str(exc)
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=504, detail=detail) from None
    except OllamaTruncatedResponseError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except OllamaGenerationError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(
            status_code=503,
            detail="Ollama could not generate the essay. Check the local model and Ollama server.",
        ) from None
    except GeminiTimeoutError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=504, detail=str(exc)) from None
    except GeminiError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ProviderConfigurationError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except IncompleteEssayError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except PiAgentTimeoutError as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=504, detail=str(exc)) from None
    except Exception as exc:
        _log_ship30_failure_if_needed(exc, payload.topic)
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            raise HTTPException(
                status_code=504,
                detail="The selected provider timed out while retrieving evidence or generating the essay. Check the provider service and configured timeout.",
            ) from None
        raise HTTPException(
            status_code=503,
            detail="Essay generation failed. Check the selected LLM provider and local retrieval service.",
        ) from None
    if not answer.grounded or not answer.sources:
        reason = answer.refusal_reason or ("answer_not_grounded" if not answer.grounded else "no_cited_sources")
        extra = {
            "event": "ship30_generation_rejected", "reason": reason,
            "topic_chars": len(payload.topic), "answer_chars": len(answer.answer),
            "source_count": len(answer.sources),
        }
        request_id = request_id_context.get()
        if request_id:
            extra["request_id"] = request_id
        logger.warning("ship30_generation_rejected", extra=extra)
        raise HTTPException(
            status_code=422,
            detail="The transcript library did not return enough relevant evidence for this essay. Try a narrower topic or focus on a subject covered in the source library.",
        )
    from app.agents.lenny_agent import _deduplicate_essay
    answer = answer.__class__(
        _deduplicate_essay(answer.answer), answer.sources, answer.grounded, answer.refusal_reason,
    )
    # Count only after normalization: this exact string is what gets persisted.
    word_count = _artifact_word_count(answer.answer, payload.artifact_format)
    if payload.artifact_format == "markdown" and word_count > 1350:
        from app.agents.lenny_agent import _trim_essay_to_word_limit
        # Leave margin for citation and Markdown tokens counted differently by the Pi adapter.
        answer = answer.__class__(
            _trim_essay_to_word_limit(answer.answer, 1250), answer.sources, answer.grounded, answer.refusal_reason,
        )
        word_count = _artifact_word_count(answer.answer, payload.artifact_format)
    word_count = _artifact_word_count(answer.answer, payload.artifact_format)
    valid_labels = {f"[{source.source_id}]" for source in answer.sources}
    citation_count = sum(1 for match in re.finditer(r"\[S\d+\]", answer.answer) if match.group(0) in valid_labels)
    minimum_words = get_settings().ship30_minimum_response_words
    if word_count > 1350:
        logger.warning(
            "ship30_validation_failed",
            extra={"event": "ship30_validation_failed", "category": "excessive_word_count",
                   "word_count": word_count, "maximum_word_count": 1350, "citation_count": citation_count},
        )
        raise HTTPException(
            status_code=503,
            detail="The Ship 30 essay exceeded the 1,350-word limit; no artifact was saved.",
        )
    if word_count < minimum_words:
        logger.warning(
            "ship30_validation_failed",
            extra={"event": "ship30_validation_failed", "category": "insufficient_word_count",
                   "word_count": word_count, "citation_count": citation_count,
                   "provider": "anthropic" if get_settings().agent_framework.strip().lower() == "claude_agent_sdk" else get_settings().llm_provider.strip().lower(),
                   "minimum_word_count": minimum_words},
        )
        if get_settings().agent_framework.strip().lower() == "pi_coding_agent":
            exc = IncompleteEssayError(
                f"Pi produced {word_count} cited words after the configured continuation attempts; "
                f"Ship 30 requires at least {minimum_words}. No artifact was saved. "
                "Try a narrower topic with more transcript coverage or increase PI_SHIP30_TIMEOUT_SECONDS."
            )
        else:
            exc = IncompleteEssayError(
                "The Ship 30 essay did not reach the configured minimum length; no artifact was saved."
            )
        _log_ship30_failure_if_needed(exc, payload.topic)
        raise HTTPException(status_code=503, detail=str(exc)) from None
    log_rag_diagnostic(
        logger, "ship30_generation_accepted", answer_chars=len(answer.answer),
        source_count=len(answer.sources), source_ids=[source.source_id for source in answer.sources],
    )
    title_match = re.search(r"(?m)^#\s+(.+)$", answer.answer)
    title = title_match.group(1).strip() if title_match else payload.topic[:240]
    artifact = ChatArtifact(
        user_id=payload.user_id, session_id=payload.session_id, title=title,
        artifact_format=payload.artifact_format, content=answer.answer,
        sources=[source.__dict__ for source in answer.sources], word_count=word_count,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


def _log_ship30_failure(error_type: str, topic: str, category: str) -> None:
    extra = {"event": "ship30_generation_failed", "error_type": error_type,
             "failure_category": category, "topic_chars": len(topic)}
    request_id = request_id_context.get()
    if request_id:
        extra["request_id"] = request_id
    logger.error("ship30_generation_failed", extra=extra)


def _log_ship30_failure_if_needed(exc: Exception, topic: str) -> None:
    if isinstance(exc, IncompleteEssayError):
        category = exc.category
    elif isinstance(exc, PiAgentTimeoutError):
        category = "pi_timeout"
    elif isinstance(exc, (GeminiError, ProviderConfigurationError, OllamaGenerationError)):
        category = "provider_error"
    else:
        category = "request_error"
    _log_ship30_failure(type(exc).__name__, topic, category)


@router.get("", response_model=list[ArtifactOut])
def list_artifacts(user_id: str = Query(min_length=8, max_length=64), db: Session = Depends(get_db)):
    return list(db.scalars(select(ChatArtifact).where(ChatArtifact.user_id == user_id).order_by(ChatArtifact.created_at.desc())).all())
