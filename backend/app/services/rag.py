"""Grounded question answering service with explicit source references."""
from dataclasses import dataclass
import logging
import re
from time import perf_counter
from app.core.rag_diagnostics import log_rag_diagnostic, log_rag_failure
from app.agents.providers import GenerationResult, LLMProvider, _generate_with_metadata
from app.rag.retrieval import Passage, Retriever

INSUFFICIENT_EVIDENCE = "I couldn't find enough relevant, traceable evidence in the indexed Lenny library to answer that question. The retrieved passages do not support a specific answer."
logger = logging.getLogger(__name__)


def _essay_word_count(text: str) -> int:
    text = re.sub(r"\[S\d+\]", " ", text)
    text = re.sub(r"[#*_>`~]", " ", text)
    return len(re.findall(r"\b[\w'-]+\b", text))


def _merge_continuation(draft: str, continuation: str) -> str:
    """Append only new Markdown paragraphs, retaining the first copy and its citations."""
    def paragraphs(text: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            heading = re.match(r"^#{1,6}\s+", line)
            if not line.strip() or heading:
                if current:
                    parts.append("\n".join(current).strip())
                    current = []
                if heading:
                    parts.append(line.strip())
            else:
                current.append(line.strip())
        if current:
            parts.append("\n".join(current).strip())
        return parts

    def normalized(paragraph: str) -> str:
        paragraph = re.sub(r"^#{1,6}\s+", "", paragraph.strip())
        paragraph = re.sub(r"[*_`~]", "", paragraph)
        return re.sub(r"\s+", " ", paragraph).strip().casefold()

    existing = paragraphs(draft)
    # Also deduplicate paragraphs already repeated within a provider response.
    def unique(parts: list[str]) -> list[str]:
        seen_parts: set[str] = set()
        result: list[str] = []
        for part in parts:
            key = normalized(part)
            if key and key not in seen_parts:
                seen_parts.add(key)
                result.append(part)
        return result

    existing = unique(existing)
    seen = {normalized(part) for part in existing}
    additions = []
    for part in paragraphs(continuation):
        key = normalized(part)
        if not key or key in seen:
            continue
        seen.add(key)
        additions.append(part)
    if not additions:
        return draft.strip()
    return "\n\n".join([*existing, *additions])


def _deduplicate_paragraphs(text: str) -> str:
    """Remove repeated paragraphs within a complete provider response."""
    merged = _merge_continuation("", text)
    return merged if merged.strip() else text.strip()


@dataclass(frozen=True)
class _ValidatedDraft:
    text: str
    used_refs: list["SourceReference"]
    sentences: list[str]
    supported_sentences: list[str]
    dropped_sentences: int
    citation_count: int
    word_count: int
    uncited_sentence_count: int
    invalid_citation_sentence_count: int
    invalid_citation_count: int


def _validate_grounded_draft(response: str, refs: list["SourceReference"], *, preserve_markdown_structure: bool) -> _ValidatedDraft:
    """Apply the strict source-ID and cited-claim filter used for essay completion."""
    valid_labels = {f"[{ref.source_id}]" for ref in refs}
    response = _normalize_source_ids(response, valid_labels)
    response = _clean_markdown(response)
    citation_count = len(re.findall(r"\[S\d+\]", response))
    sentences = [
        part.strip() for part in re.split(r"(?<=[.!?])\s+(?!\[S\d+\])|(?<=\])\s+|\n+", response.strip())
        if part.strip()
    ]
    used_ids: set[str] = set()
    supported_sentences: list[str] = []
    dropped_sentences = 0
    uncited_sentence_count = 0
    invalid_citation_sentence_count = 0
    invalid_citation_count = 0
    for sentence in sentences:
        if preserve_markdown_structure and re.match(r"^#{1,6}\s+\S", sentence):
            supported_sentences.append(sentence)
            continue
        labels = re.findall(r"\[(S\d+)\]", sentence)
        valid_ids = {label for label in labels if f"[{label}]" in valid_labels}
        invalid_ids = [label for label in labels if f"[{label}]" not in valid_labels]
        invalid_citation_count += len(invalid_ids)
        if not valid_ids:
            dropped_sentences += 1
            if labels:
                invalid_citation_sentence_count += 1
            else:
                uncited_sentence_count += 1
            continue
        sentence = re.sub(r"\[S\d+\]", lambda match: match.group(0) if match.group(0) in valid_labels else "", sentence).strip()
        supported_sentences.append(sentence)
        used_ids.update(valid_ids)
    text = "\n".join(supported_sentences).strip()
    prose = re.sub(r"\[S\d+\]", " ", text)
    prose = re.sub(r"[#*_>`~]", " ", prose)
    word_count = len(re.findall(r"\b[\w'-]+\b", prose))
    return _ValidatedDraft(
        text=text,
        used_refs=[ref for ref in refs if ref.source_id in used_ids],
        sentences=sentences,
        supported_sentences=supported_sentences,
        dropped_sentences=dropped_sentences,
        citation_count=len(re.findall(r"\[S\d+\]", text)),
        word_count=word_count,
        uncited_sentence_count=uncited_sentence_count,
        invalid_citation_sentence_count=invalid_citation_sentence_count,
        invalid_citation_count=invalid_citation_count,
    )


class IncompleteEssayError(RuntimeError):
    """An essay did not meet its validated completeness requirements."""

    def __init__(self, message: str, *, category: str = "insufficient_word_count"):
        super().__init__(message)
        self.category = category



def _normalize_source_ids(text: str, valid_labels: set[str]) -> str:
    """Accept plain source IDs emitted by local models and render them as citations."""
    def normalize_group(match: re.Match) -> str:
        ids = re.findall(r"S\d+", match.group(1))
        valid_ids = [source_id for source_id in ids if f"[{source_id}]" in valid_labels]
        # Keep claims with at least one real source label while removing only
        # unknown IDs from a grouped citation. No source label is synthesized.
        return " ".join(f"[{source_id}]" for source_id in valid_ids) if valid_ids else match.group(0)

    text = re.sub(r"\[((?:S\d+)(?:\s*,\s*S\d+)+)\]", normalize_group, text)

    def replace_range(match: re.Match) -> str:
        start, end = int(match.group(1)), int(match.group(2))
        labels = [f"S{number}" for number in range(start, end + 1)]
        if end >= start and end - start <= 4 and all(f"[{label}]" in valid_labels for label in labels):
            return " ".join(f"[{label}]" for label in labels)
        return match.group(0)

    text = re.sub(r"(?<![\w\[])S(\d+)\s*[-–]\s*S(\d+)(?!\w)", replace_range, text)
    return re.sub(
        r"(?<![\w\[])S(\d+)(?!\w)",
        lambda match: f"[{match.group(0)}]" if f"[{match.group(0)}]" in valid_labels else match.group(0),
        text,
    )


def _clean_markdown(text: str) -> str:
    """Normalize common model list artifacts while preserving ordinary Markdown."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        # Models sometimes wrap a list item in a quote or nest two bullet markers.
        line = re.sub(r"^[-*+]\s+[\"']?", "", line)
        line = re.sub(r"^(?:[-*+]\s+)+", "- ", line)
        line = re.sub(r"[\"']+$", "", line)
        line = re.sub(r"([.!?])\s*[\"']+$", r"\1", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


@dataclass(frozen=True)
class SourceReference:
    source_id: str
    title: str
    document_type: str
    source_path: str
    url: str | None
    chunk_id: str


@dataclass(frozen=True)
class Answer:
    answer: str
    sources: list[SourceReference]
    # Means every retained claim has a citation that maps to a retrieved source.
    # It does not claim an independent semantic entailment check was performed.
    grounded: bool
    refusal_reason: str | None = None


def _traceable_passages(passages: list[Passage]) -> list[tuple[SourceReference, Passage]]:
    refs: list[tuple[SourceReference, Passage]] = []
    seen: set[tuple[str, str]] = set()
    for passage in passages:
        metadata = passage.metadata
        key = (str(metadata.get("source_path", "")), str(metadata.get("chunk_id", "")))
        if key in seen or not key[0] or not key[1]:
            continue
        seen.add(key)
        ref = SourceReference(
            source_id=f"S{len(refs) + 1}", title=str(metadata.get("title", "Untitled source")),
            document_type=str(metadata.get("document_type", "document")), source_path=key[0],
            url=str(metadata["post_url"]) if metadata.get("post_url") else None, chunk_id=key[1],
        )
        refs.append((ref, passage))
    return refs


def source_references(passages: list[Passage]) -> list[SourceReference]:
    return [ref for ref, _ in _traceable_passages(passages)]


class RAGService:
    MAX_CONTEXT_PASSAGES = 3
    MAX_CONTEXT_CHARS_PER_PASSAGE = 850

    def __init__(
        self, retriever: Retriever, llm: LLMProvider, *,
        max_context_passages: int = MAX_CONTEXT_PASSAGES,
        max_context_chars_per_passage: int = MAX_CONTEXT_CHARS_PER_PASSAGE,
        preserve_markdown_structure: bool = False,
        compact_context: bool = False,
        minimum_response_words: int = 0,
        target_response_words: int = 0,
        max_continuations: int = 0,
    ):
        self.retriever, self.llm = retriever, llm
        self.max_context_passages = max_context_passages
        self.max_context_chars_per_passage = max_context_chars_per_passage
        self.preserve_markdown_structure = preserve_markdown_structure
        self.compact_context = compact_context
        self.minimum_response_words = minimum_response_words
        self.target_response_words = target_response_words
        # Bound Ship 30 to one initial call plus at most three continuations.
        self.max_continuations = min(max(0, max_continuations), 3)

    def answer(
        self, question: str, *, system_prompt: str | None = None,
        retrieval_query: str | None = None,
    ) -> Answer:
        stage_started = perf_counter()
        try:
            passages = self.retriever.retrieve(retrieval_query if retrieval_query is not None else question)
        except Exception as exc:
            log_rag_failure(logger, "RAG retrieval stage failed", stage="retrieve", exc=exc, stage_elapsed_ms=round((perf_counter() - stage_started) * 1000, 2))
            raise
        log_rag_diagnostic(logger, "rag_stage_complete", stage="retrieve", stage_elapsed_ms=round((perf_counter() - stage_started) * 1000, 2))
        cited_passages = _traceable_passages(passages)
        traceable_count = len(cited_passages)
        cited_passages = cited_passages[:self.max_context_passages]
        log_rag_diagnostic(
            logger, "rag_evidence_ready", retriever_id=id(self.retriever), passage_count=len(passages),
            source_count=len(cited_passages), context_passage_count=len(cited_passages),
            context_dropped_count=max(0, traceable_count - len(cited_passages)),
            context_sources=[
                {"source_id": ref.source_id, "source_path": ref.source_path, "chunk_id": ref.chunk_id}
                for ref, _passage in cited_passages
            ],
        )
        if not cited_passages:
            log_rag_diagnostic(logger, "rag_answer_refused", reason="no_passages" if not passages else "no_traceable_sources")
            return Answer(INSUFFICIENT_EVIDENCE, [], False)
        refs = [ref for ref, _ in cited_passages]
        context_texts = [
            passage.text[:self.max_context_chars_per_passage].rsplit(" ", 1)[0]
            for _ref, passage in cited_passages
        ]
        if self.compact_context:
            labels = ", ".join(f"[{ref.source_id}]" for ref, _passage in cited_passages)
            context = f"Available citation labels: {labels}\n\n" + "\n\n".join(
                f"[{ref.source_id}] {ref.title}\n{text}"
                for (ref, _passage), text in zip(cited_passages, context_texts)
            )
        else:
            context = "\n\n".join(
                f"<source id=\"{ref.source_id}\" title=\"{ref.title}\" type=\"{ref.document_type}\" path=\"{ref.source_path}\">\n{text}\n</source>"
                for (ref, _passage), text in zip(cited_passages, context_texts)
            )
        log_rag_diagnostic(
            logger, "rag_context_formatted", context_passage_count=len(cited_passages),
            context_truncated_count=sum(len(passage.text) > self.max_context_chars_per_passage for _, passage in cited_passages),
            context_char_count=len(context), context_char_limit=self.max_context_chars_per_passage,
        )
        system = system_prompt or (
            "Answer directly using only supplied source passages and only claims they explicitly support. "
            "For each supported strategy, give a specific recommendation and explain its importance using evidence in the passage. "
            "Write up to three distinct, useful bullets. Vary sentence structure naturally; do not repeat a fixed 'Strategy / This matters because' template. "
            "Cite every factual sentence immediately with the source ID(s) that directly support it, such as [S1]. "
            "Do not cite a source merely because it is relevant to the topic. Do not make a claim broader than its "
            "supporting passage. If fewer than three lessons are supported, give only those supported and clearly "
            "say what requested detail the available evidence does not establish. If the passages are off-topic or too thin for a useful recommendation, say the evidence is insufficient instead of filling the requested bullet count. Label a deduction as 'Inference:' only when it follows directly from cited evidence; otherwise omit it. "
            "If no useful claim is supported, state that the "
            "retrieved evidence is insufficient. Do not use uncited factual claims. Format every supported lesson as "
            "one Markdown bullet per strategy; cite each factual sentence immediately and use only sources that directly support that sentence. "
            "Do not surround bullets or their text with quotation marks, and do not nest redundant bullet markers. "
            "Do not write an introduction, refer to source IDs as plain text, or add implications."
        )
        generation_prompt = f"Question: {question}\n\nRetrieved evidence:\n{context}"
        retry_count = 0
        generation_elapsed_ms = 0.0
        output_tokens = 0
        input_tokens = 0
        total_tokens = 0

        def generate_once(prompt: str, attempt_number: int) -> GenerationResult:
            started = perf_counter()
            try:
                result = _generate_with_metadata(self.llm, system, prompt)
            except Exception as exc:
                elapsed = round((perf_counter() - started) * 1000, 2)
                if self.minimum_response_words:
                    logger.error(
                        "ship30_generation_failed",
                        extra={"event": "ship30_generation_failed", "failure_category": "provider_error",
                               "selected_provider": getattr(self.llm, "provider_name", type(self.llm).__name__),
                               "provider": getattr(self.llm, "provider_name", type(self.llm).__name__),
                               "model": getattr(self.llm, "model_name", "unknown"),
                               "elapsed_ms": elapsed, "attempt_number": attempt_number,
                               "retry_count": attempt_number - 1,
                               "error_type": type(exc).__name__},
                    )
                log_rag_failure(logger, "RAG answer generation stage failed", stage="generate", exc=exc, stage_elapsed_ms=elapsed)
                raise
            return result

        def validate_draft(text: str) -> _ValidatedDraft:
            validated = _validate_grounded_draft(
                text, refs, preserve_markdown_structure=self.preserve_markdown_structure,
            )
            if self.minimum_response_words:
                from app.agents.lenny_agent import _filter_specific_claims
                evidence_by_id = {ref.source_id: passage.text for ref, passage in cited_passages}
                filtered = _filter_specific_claims(validated.text, evidence_by_id)
                if filtered != validated.text:
                    validated = _validate_grounded_draft(
                        filtered, refs, preserve_markdown_structure=self.preserve_markdown_structure,
                    )
            return validated

        def log_attempt(
            result: GenerationResult, attempt_number: int, response_validation: _ValidatedDraft,
            essay_validation: _ValidatedDraft, continuation_word_count: int,
        ) -> None:
            if not self.minimum_response_words:
                return
            raw_word_count = _essay_word_count(result.text)
            logger.info(
                "ship30_generation_attempt_complete",
                extra={
                    "event": "ship30_generation_attempt_complete",
                    "selected_provider": getattr(self.llm, "provider_name", result.provider),
                    "provider": result.provider, "model": result.model,
                    "attempt_number": attempt_number, "retry_count": attempt_number - 1,
                    "elapsed_ms": result.elapsed_ms, "output_chars": len(result.text),
                    "raw_word_count": raw_word_count,
                    "validated_word_count": response_validation.word_count,
                    "final_word_count": essay_validation.word_count,
                    "continuation_word_count": continuation_word_count,
                    "words_removed_by_validation": max(0, raw_word_count - response_validation.word_count),
                    "uncited_sentence_count": response_validation.uncited_sentence_count,
                    "invalid_citation_sentence_count": response_validation.invalid_citation_sentence_count,
                    "invalid_citation_count": response_validation.invalid_citation_count,
                    "citation_count": response_validation.citation_count,
                    "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                    "configured_output_token_limit": result.configured_output_token_limit,
                    "finish_reason": result.finish_reason, "truncated": result.truncated,
                    "max_continuations": self.max_continuations,
                    "max_generation_calls": 1 + self.max_continuations,
                },
            )

        attempt_number = 1
        generation_meta = generate_once(generation_prompt, attempt_number)
        response = generation_meta.text
        validated = validate_draft(response)
        first_response_word_count = _essay_word_count(response)
        first_response_output_tokens = generation_meta.output_tokens
        first_finish_reason = generation_meta.finish_reason
        first_finish_truncated = generation_meta.truncated
        generation_elapsed_ms += generation_meta.elapsed_ms
        output_tokens += generation_meta.output_tokens or 0
        input_tokens += generation_meta.input_tokens or 0
        total_tokens += generation_meta.total_tokens or 0
        log_attempt(generation_meta, attempt_number, validated, validated, 0)
        no_progress_count = 0

        # A draft can need several moderate continuations. Limit the entire
        # operation to the configured small number, carrying only the strictly
        # cited draft and the exact validated word gap into each call.
        target_words = self.target_response_words or self.minimum_response_words
        maximum_words = 1350 if self.minimum_response_words else target_words
        while (
            self.minimum_response_words
            and retry_count < self.max_continuations
            and validated.word_count < target_words
        ):
            remaining_words = max(0, target_words - validated.word_count)
            prior_word_count = validated.word_count
            attempt_number += 1
            continuation_system = system
            if continuation_system:
                continuation_system += " For a continuation, return only new paragraphs; do not repeat material already present in the supplied validated draft."
            continuation_prompt = (
                f"{generation_prompt}\n\nCurrent citation-validated essay draft (preserve it; do not repeat it):\n"
                f"<draft>\n{validated.text}\n</draft>\n\n"
                "Return only new paragraphs; do not repeat material already present in the supplied validated draft. "
                f"The validated draft currently has {prior_word_count} essay words. Add approximately "
                f"{remaining_words} new, supported words to reach about {target_words} essay words total. "
                "Continue from its ending, complete the requested narrative progression, and return only new paragraphs. "
                "Do not repeat the introduction, existing claims, or existing headings. If the evidence cannot support more material, "
                "stop rather than padding. Cite every factual sentence using only the exact available source labels; omit claims "
                "the retrieved evidence cannot support."
            )
            original_system = system
            system = continuation_system
            try:
                continued = generate_once(continuation_prompt, attempt_number)
            finally:
                system = original_system
            retry_count += 1
            continuation_validation = validate_draft(continued.text)
            merged_text = _merge_continuation(validated.text, continuation_validation.text)
            merged_validation = validate_draft(merged_text)
            continuation_word_count = max(0, merged_validation.word_count - prior_word_count)
            log_attempt(continued, attempt_number, continuation_validation, merged_validation, continuation_word_count)
            if continuation_word_count == 0:
                no_progress_count += 1
            else:
                no_progress_count = 0
            response = merged_text
            validated = merged_validation
            generation_elapsed_ms += continued.elapsed_ms
            output_tokens += continued.output_tokens or 0
            input_tokens += continued.input_tokens or 0
            total_tokens += continued.total_tokens or 0
            generation_meta = continued
            if no_progress_count >= 2:
                logger.warning(
                    "ship30_continuation_stopped",
                    extra={"event": "ship30_continuation_stopped", "reason": "repeated_no_progress",
                           "provider": continued.provider, "model": continued.model,
                           "attempt_number": attempt_number, "retry_count": retry_count,
                           "final_word_count": validated.word_count,
                           "continuation_word_count": continuation_word_count,
                           "no_progress_count": no_progress_count},
                )
                break

        # Keep a generous but explicit upper bound on persisted Ship 30 prose.
        # Trim whole cited paragraphs only; never cut a claim away from its citation.
        if self.minimum_response_words and validated.word_count > maximum_words:
            kept: list[str] = []
            for block in re.split(r"\n\s*\n", validated.text):
                candidate = "\n\n".join([*kept, block])
                if _essay_word_count(candidate) <= maximum_words or not kept:
                    kept.append(block)
                else:
                    break
            bounded = validate_draft("\n\n".join(kept))
            if bounded.word_count >= self.minimum_response_words:
                validated = bounded
                response = bounded.text

        if self.minimum_response_words:
            logger.info(
                "ship30_generation_complete",
                extra={"event": "ship30_generation_complete",
                       "selected_provider": getattr(self.llm, "provider_name", generation_meta.provider),
                       "provider": generation_meta.provider, "model": generation_meta.model,
                       "elapsed_ms": generation_elapsed_ms, "output_chars": len(response),
                       "input_tokens": input_tokens or None, "output_tokens": output_tokens or None,
                       "total_tokens": total_tokens or None, "retry_count": retry_count,
                       "attempt_count": retry_count + 1,
                       "max_continuations": self.max_continuations,
                       "max_generation_calls": 1 + self.max_continuations,
                       "configured_output_token_limit": generation_meta.configured_output_token_limit,
                       "first_response_word_count": first_response_word_count,
                       "final_word_count": validated.word_count,
                       "first_response_output_tokens": first_response_output_tokens,
                       "finish_reason": generation_meta.finish_reason,
                       "first_finish_reason": first_finish_reason,
                       "first_truncated": first_finish_truncated,
                       "truncated": generation_meta.truncated,
                       "no_progress_count": no_progress_count},
            )
        log_rag_diagnostic(logger, "rag_stage_complete", stage="generate", stage_elapsed_ms=generation_elapsed_ms)
        response_char_count = len(response)
        response = validated.text
        sentences = validated.sentences
        supported_sentences = validated.supported_sentences
        dropped_sentences = validated.dropped_sentences
        used_refs = validated.used_refs
        word_count = validated.word_count
        citation_count = validated.citation_count
        if not response or not used_refs:
            logger.warning(
                "ship30_validation_failed",
                extra={
                    "event": "ship30_validation_failed", "category": "missing_valid_citations",
                    "word_count": word_count, "citation_count": citation_count,
                    "first_response_word_count": first_response_word_count,
                    "final_word_count": word_count,
                        "provider": generation_meta.provider, "model": generation_meta.model,
                        "elapsed_ms": generation_elapsed_ms, "output_chars": len(response),
                        "output_tokens": output_tokens or None, "retry_count": retry_count,
                },
            )
            log_rag_diagnostic(
                logger, "rag_answer_refused",
                reason="empty_provider_response" if response_char_count == 0 else "no_cited_supported_claims",
                response_empty=True, response_char_count=response_char_count,
                validation_sentence_count=len(sentences),
                validation_supported_count=len(supported_sentences),
                validation_rejection="no_valid_cited_claim",
            )
            return Answer(INSUFFICIENT_EVIDENCE, [], False)
        if self.minimum_response_words:
            if word_count < self.minimum_response_words:
                logger.warning(
                    "ship30_validation_failed",
                    extra={
                        "event": "ship30_validation_failed", "category": "insufficient_word_count",
                        "word_count": word_count, "citation_count": citation_count,
                        "first_response_word_count": first_response_word_count,
                        "final_word_count": word_count,
                        "provider": generation_meta.provider, "model": generation_meta.model,
                        "elapsed_ms": generation_elapsed_ms, "output_chars": len(response),
                        "output_tokens": output_tokens or None, "retry_count": retry_count,
                    },
                )
                raise IncompleteEssayError("The Ship 30 essay did not reach the configured minimum length; no artifact was saved.")
            if generation_meta.truncated:
                logger.warning(
                    "ship30_validation_failed",
                    extra={"event": "ship30_validation_failed", "category": "truncated_output",
                           "word_count": word_count, "citation_count": citation_count,
                           "first_response_word_count": first_response_word_count,
                           "final_word_count": word_count,
                           "provider": generation_meta.provider, "model": generation_meta.model,
                           "elapsed_ms": generation_elapsed_ms, "output_chars": len(response),
                           "output_tokens": output_tokens or None, "retry_count": retry_count},
                )
                raise IncompleteEssayError(
                    "The Ship 30 essay was still truncated after its continuation; no artifact was saved.",
                    category="truncated_output",
                )
            log_rag_diagnostic(
                logger, "ship30_validation_passed", category="grounded_minimum_met",
                word_count=word_count, citation_count=citation_count,
                first_response_word_count=first_response_word_count, final_word_count=word_count,
                provider=generation_meta.provider, model=generation_meta.model,
                elapsed_ms=generation_elapsed_ms, output_chars=len(response),
                output_tokens=output_tokens or None, retry_count=retry_count,
            )
        log_rag_diagnostic(
            logger, "rag_answer_grounded", validation_sentence_count=len(sentences),
            validation_supported_count=len(supported_sentences), validation_dropped_count=dropped_sentences,
            source_count=len(used_refs),
        )
        return Answer(response, used_refs, True)
