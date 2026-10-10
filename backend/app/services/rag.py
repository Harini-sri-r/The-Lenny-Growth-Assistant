"""Grounded question answering service with explicit source references."""
from dataclasses import dataclass
import logging
import re
from time import perf_counter
from app.core.rag_diagnostics import log_rag_diagnostic, log_rag_failure
from app.agents.providers import LLMProvider
from app.rag.retrieval import Passage, Retriever

INSUFFICIENT_EVIDENCE = "I couldn't find enough relevant, traceable evidence in the indexed Lenny library to answer that question. The retrieved passages do not support a specific answer."
logger = logging.getLogger(__name__)


def _normalize_source_ids(text: str, valid_labels: set[str]) -> str:
    """Accept plain source IDs emitted by local models and render them as citations."""
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
    grounded: bool


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

    def __init__(self, retriever: Retriever, llm: LLMProvider):
        self.retriever, self.llm = retriever, llm

    def answer(self, question: str) -> Answer:
        stage_started = perf_counter()
        try:
            passages = self.retriever.retrieve(question)
        except Exception as exc:
            log_rag_failure(logger, "RAG retrieval stage failed", stage="retrieve", exc=exc, stage_elapsed_ms=round((perf_counter() - stage_started) * 1000, 2))
            raise
        log_rag_diagnostic(logger, "rag_stage_complete", stage="retrieve", stage_elapsed_ms=round((perf_counter() - stage_started) * 1000, 2))
        cited_passages = _traceable_passages(passages)
        traceable_count = len(cited_passages)
        cited_passages = cited_passages[:self.MAX_CONTEXT_PASSAGES]
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
            passage.text[:self.MAX_CONTEXT_CHARS_PER_PASSAGE].rsplit(" ", 1)[0]
            for _ref, passage in cited_passages
        ]
        context = "\n\n".join(
            f"<source id=\"{ref.source_id}\" title=\"{ref.title}\" type=\"{ref.document_type}\" path=\"{ref.source_path}\">\n"
            f"{text}{' …' if len(passage.text) > self.MAX_CONTEXT_CHARS_PER_PASSAGE else ''}\n</source>"
            for (ref, passage), text in zip(cited_passages, context_texts)
        )
        log_rag_diagnostic(
            logger, "rag_context_formatted", context_passage_count=len(cited_passages),
            context_truncated_count=sum(len(passage.text) > self.MAX_CONTEXT_CHARS_PER_PASSAGE for _, passage in cited_passages),
            context_char_count=len(context), context_char_limit=self.MAX_CONTEXT_CHARS_PER_PASSAGE,
        )
        system = (
            "Answer directly using only supplied source passages and only claims the passage states. For lessons, "
            "write up to three distinct, concise one-sentence bullets when supported. "
            "Cite every factual sentence immediately with the source ID(s) that directly support it, such as [S1]. "
            "Do not cite a source merely because it is relevant to the topic. Do not make a claim broader than its "
            "supporting passage. If fewer than three lessons are supported, give only those supported and clearly "
            "say what the available evidence does not establish. If no useful claim is supported, state that the "
            "retrieved evidence is insufficient. Do not use uncited factual claims. Format every supported lesson as "
            "one short bullet with its bracketed citation at the end, such as '- A supported lesson. [S1]'. "
            "Do not write an introduction, refer to source IDs as plain text, or add implications."
        )
        stage_started = perf_counter()
        try:
            response = self.llm.generate(system, f"Question: {question}\n\nSource passages:\n{context}")
        except Exception as exc:
            log_rag_failure(logger, "RAG answer generation stage failed", stage="generate", exc=exc, stage_elapsed_ms=round((perf_counter() - stage_started) * 1000, 2))
            raise
        log_rag_diagnostic(logger, "rag_stage_complete", stage="generate", stage_elapsed_ms=round((perf_counter() - stage_started) * 1000, 2))
        response_char_count = len(response)
        valid_labels = {f"[{ref.source_id}]" for ref in refs}
        response = _normalize_source_ids(response, valid_labels)
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+(?!\[S\d+\])|\n+", response.strip()) if part.strip()]
        used_ids: set[str] = set()
        supported_sentences = []
        dropped_sentences = 0
        for sentence in sentences:
            labels = re.findall(r"\[(S\d+)\]", sentence)
            valid_ids = {label for label in labels if f"[{label}]" in valid_labels}
            # Any factual sentence without at least one recognized source is not
            # eligible for a grounded answer; omit it while retaining supported
            # claims so an uncited model preamble cannot discard useful evidence.
            if not valid_ids:
                dropped_sentences += 1
                continue
            sentence = re.sub(r"\[S\d+\]", lambda match: match.group(0) if match.group(0) in valid_labels else "", sentence).strip()
            supported_sentences.append(sentence)
            used_ids.update(valid_ids)
        response = " ".join(supported_sentences).strip()
        used_refs = [ref for ref in refs if ref.source_id in used_ids]
        if not response or not used_refs:
            log_rag_diagnostic(
                logger, "rag_answer_refused",
                reason="empty_provider_response" if response_char_count == 0 else "no_cited_supported_claims",
                response_empty=True, response_char_count=response_char_count,
                validation_sentence_count=len(sentences),
                validation_supported_count=len(supported_sentences),
                validation_rejection="no_valid_cited_claim",
            )
            return Answer(INSUFFICIENT_EVIDENCE, [], False)
        log_rag_diagnostic(
            logger, "rag_answer_grounded", validation_sentence_count=len(sentences),
            validation_supported_count=len(supported_sentences), validation_dropped_count=dropped_sentences,
            source_count=len(used_refs),
        )
        return Answer(response, used_refs, True)
