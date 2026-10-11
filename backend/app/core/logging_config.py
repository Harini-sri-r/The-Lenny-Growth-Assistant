"""Structured JSON logs without request bodies, prompts, or transcript text."""
import json
import logging
import re
import traceback
from datetime import datetime, timezone


def _safe_exception_message(value: str) -> str:
    """Remove common credential forms and cap provider-controlled error text."""
    value = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", value)
    value = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", value)
    return value[:400]


def _exception_diagnostics(exc_info) -> tuple[list[dict], list[dict]]:
    """Return safe exception summaries and frame locations without source lines."""
    if not exc_info or not exc_info[1]:
        return [], []
    summaries = []
    frames = []
    current = exc_info[1]
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        summaries.append({
            "type": type(current).__name__,
            "message": _safe_exception_message(str(current)),
        })
        tb = current.__traceback__
        while tb:
            code = tb.tb_frame.f_code
            frames.append({"file": code.co_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], "line": tb.tb_lineno, "function": code.co_name})
            tb = tb.tb_next
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return summaries, frames[-24:]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        for key in (
            "request_id", "method", "route", "status_code", "elapsed_ms", "error_type",
            "cwd", "chroma_path", "collection", "record_count", "agent_framework",
            "llm_provider", "embedding_model", "top_k", "similarity_threshold",
            "retriever_id", "raw_count", "filtered_count", "candidate_count", "passage_count",
            "source_count", "tool_calls", "response_empty", "response_char_count", "reason", "llm_model",
            "stage", "stage_elapsed_ms",
            "query_variant_count", "query_metrics", "candidate_count", "threshold_count",
            "podcast_filtered_count", "duplicate_source_count", "retained_passages",
            "podcast_only", "context_passage_count", "context_dropped_count", "context_sources",
            "validation_sentence_count", "validation_supported_count", "validation_rejection",
            "validation_dropped_count", "category", "word_count",
            "context_truncated_count", "context_char_count", "context_char_limit",
            "query_kind", "relevance_scores", "topic_chars", "answer_chars", "source_ids",
            "citation_count", "recognized_labels", "unrecognized_labels",
            "response_source", "assistant_message_count", "result_message_count", "text_block_count",
            "content_block_types", "response_kind", "response_chars", "retried", "retry_count",
            "selected_provider", "provider", "model", "attempt_number", "attempt_count",
            "raw_word_count", "validated_word_count", "final_word_count", "continuation_word_count",
            "words_removed_by_validation", "uncited_sentence_count", "invalid_citation_sentence_count",
            "invalid_citation_count", "output_chars", "output_words", "input_tokens", "output_tokens",
            "total_tokens", "first_response_word_count", "first_response_output_tokens",
            "continuation_output_tokens", "configured_output_token_limit", "finish_reason",
            "first_finish_reason", "truncated", "first_truncated", "max_continuations",
            "max_generation_calls", "no_progress_count", "dropped_sentences", "elapsed_ms",
            "failure_message", "failure_category", "stderr_category", "sdk_error_category", "sdk_error_count", "exit_code", "api_error_status",
            "terminal_reason", "subtype",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            exceptions, frames = _exception_diagnostics(record.exc_info)
            payload["exceptions"] = exceptions
            payload["traceback"] = frames
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
