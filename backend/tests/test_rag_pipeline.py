import json
import logging
from pathlib import Path

import pytest

from app.agents.providers import LLMProvider
from app.rag.documents import Document, chunk_document, load_documents
from app.rag.indexer import index_corpus
from app.rag.retrieval import Retriever
from app.services.rag import INSUFFICIENT_EVIDENCE, RAGService, source_references


class FakeEmbeddings:
    def __init__(self, *, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("synthetic embedding failure")
        return [[float(len(text)), 1.0] for text in texts]


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self.cleared = False

    def upsert(self, ids, texts, metadatas, embeddings):
        for id_, text, metadata, embedding in zip(ids, texts, metadatas, embeddings):
            self.rows[id_] = {"text": text, "metadata": metadata, "embedding": embedding}

    def get_records(self, ids):
        return {id_: {"text": self.rows[id_]["text"], "metadata": self.rows[id_]["metadata"]} for id_ in ids if id_ in self.rows}

    def delete_except(self, ids):
        self.rows = {key: value for key, value in self.rows.items() if key in ids}

    def query(self, embedding, top_k):
        def cosine(left, right):
            dot = sum(a * b for a, b in zip(left, right))
            denom = (sum(a * a for a in left) ** .5) * (sum(b * b for b in right) ** .5)
            return dot / denom if denom else 0.0
        matches = sorted(self.rows.values(), key=lambda row: cosine(embedding, row["embedding"]), reverse=True)[:top_k]
        return [{"text": row["text"], "metadata": row["metadata"], "similarity": cosine(embedding, row["embedding"])} for row in matches]

    def embedding_dimensions(self):
        return len(next(iter(self.rows.values()))["embedding"]) if self.rows else None

    def clear(self):
        self.rows.clear()
        self.cleared = True


class FakeLLM(LLMProvider):
    def __init__(self):
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return "The indexed passage says this. [S1]"


@pytest.fixture
def dataset(tmp_path):
    (tmp_path / "podcasts").mkdir()
    (tmp_path / "newsletters").mkdir()
    (tmp_path / "podcasts" / "guest.md").write_text("---\ntitle: Front matter\n---\n\nA useful product passage with enough words to chunk reliably.", encoding="utf-8")
    (tmp_path / "newsletters" / "essay.md").write_text("Newsletter body about product strategy and prioritization.", encoding="utf-8")
    index = {"podcasts": [{"filename": "podcasts/guest.md", "title": "Guest episode", "guest": "Guest", "date": "2025-01-01", "post_url": "https://example.test/episode"}], "newsletters": [{"filename": "newsletters/essay.md", "title": "Newsletter", "subtitle": "An essay"}]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return tmp_path


def test_load_clean_metadata_and_chunk_identifiers(dataset):
    docs = load_documents(dataset)
    podcast = next(doc for doc in docs if doc.metadata["document_type"] == "podcast")
    assert podcast.text.startswith("A useful product passage")
    assert podcast.metadata["title"] == "Guest episode"
    assert podcast.metadata["source_path"] == "podcasts/guest.md"
    assert podcast.metadata["post_url"] == "https://example.test/episode"
    chunks = chunk_document(podcast, size=25, overlap=5)
    assert len(chunks) > 1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["chunk_id"] == chunk_document(podcast, size=25, overlap=5)[0].metadata["chunk_id"]


def test_chunking_applies_configured_overlap():
    doc = Document("abcdefghijklmnopqrstuvwxyz", {"source_path": "sample.md"})
    chunks = chunk_document(doc, size=10, overlap=3)
    assert chunks[0].text[-3:] == chunks[1].text[:3]


def test_unsupported_or_missing_index_is_not_silently_skipped(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_documents(tmp_path)


def test_incremental_index_skips_compatible_chunks_and_indexes_missing_ids(dataset):
    store, embeddings = MemoryStore(), FakeEmbeddings()
    count = index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    assert count == len(store.rows)
    original_ids = set(store.rows)
    existing_id = next(iter(original_ids))
    del store.rows[existing_id]
    before = len(embeddings.calls)
    index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    assert len(embeddings.calls) == before + 1
    assert set(store.rows) == original_ids


def test_incremental_index_is_idempotent_and_cleans_stale_records(dataset):
    store, embeddings = MemoryStore(), FakeEmbeddings()
    count = index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    original_ids = set(store.rows)
    store.rows["obsolete"] = {"text": "old", "metadata": {}, "embedding": [0, 0]}
    before = len(embeddings.calls)
    index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    assert len(embeddings.calls) == before
    assert set(store.rows) == original_ids
    assert len(store.rows) == count


def test_same_id_with_incompatible_chunking_metadata_is_reembedded(dataset):
    store, embeddings = MemoryStore(), FakeEmbeddings()
    count = index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    first_id = next(iter(store.rows))
    store.rows[first_id]["metadata"].pop("chunk_size")
    before = len(embeddings.calls)
    index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    assert len(embeddings.calls) == before + 1
    assert store.rows[first_id]["metadata"]["chunk_size"] == 32
    assert len(store.rows) == count


def test_index_repeatably_upserts_and_reindex_clears(dataset):
    store, embeddings = MemoryStore(), FakeEmbeddings()
    count = index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4)
    original_ids = set(store.rows)
    index_corpus(dataset, store, embeddings, chunk_size=32, chunk_overlap=4, reindex=True)
    assert store.cleared
    assert set(store.rows) == original_ids


def test_index_uses_configured_batch_size_and_reports_progress(dataset, caplog):
    store, embeddings = MemoryStore(), FakeEmbeddings()
    with caplog.at_level(logging.INFO, logger="app.rag.indexer"):
        count = index_corpus(dataset, store, embeddings, chunk_size=20, chunk_overlap=2, batch_size=3)

    assert count == len(store.rows)
    assert len(embeddings.calls) == (count + 2) // 3
    assert all(1 <= len(batch) <= 3 for batch in embeddings.calls)
    assert "total_chunks=" in caplog.text
    assert "Embedding batch 1/" in caplog.text
    assert "load_seconds=" in caplog.text
    assert "chunk_seconds=" in caplog.text
    assert "embedding_seconds=" in caplog.text
    assert "chroma_write_seconds=" in caplog.text
    assert "stale_cleanup_seconds=" in caplog.text
    assert "total_elapsed_seconds=" in caplog.text


def test_interrupted_index_resumes_with_upserts_without_duplicates(dataset):
    store = MemoryStore()
    failed_embeddings = FakeEmbeddings(fail_on_call=2)
    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        index_corpus(dataset, store, failed_embeddings, chunk_size=20, chunk_overlap=2, batch_size=2)

    first_run_ids = set(store.rows)
    assert first_run_ids
    assert not store.cleared

    embeddings = FakeEmbeddings()
    count = index_corpus(dataset, store, embeddings, chunk_size=20, chunk_overlap=2, batch_size=2)
    assert len(store.rows) == count
    assert len(set(store.rows)) == count
    assert set(store.rows).issuperset(first_run_ids)
    assert not store.cleared


def test_index_logs_and_reraises_embedding_failure(dataset, caplog):
    with caplog.at_level(logging.ERROR, logger="app.rag.indexer"):
        with pytest.raises(RuntimeError, match="synthetic embedding failure"):
            index_corpus(dataset, MemoryStore(), FakeEmbeddings(fail_on_call=1), chunk_size=20, chunk_overlap=2, batch_size=2)

    assert "Transcript indexing failed" in caplog.text
    assert "chunks=1-2/" in caplog.text
    assert "total_elapsed_seconds=" in caplog.text


def test_failed_index_does_not_clean_stale_records(dataset):
    store = MemoryStore()
    store.rows["preexisting-stale-id"] = {"text": "keep until full success", "metadata": {}, "embedding": [0.0, 0.0]}

    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        index_corpus(dataset, store, FakeEmbeddings(fail_on_call=1), chunk_size=20, chunk_overlap=2, batch_size=2)

    assert "preexisting-stale-id" in store.rows


def test_embedding_timeout_must_be_positive():
    from app.rag.embeddings import OllamaEmbeddings

    with pytest.raises(ValueError, match="timeout must be positive"):
        OllamaEmbeddings("http://localhost:11434", "nomic-embed-text", timeout=0)


def test_retrieval_threshold_and_empty_query():
    store = MemoryStore()
    store.upsert(["strong", "weak"], ["strong source", "weak source"], [{"source_path": "a.md", "chunk_id": "strong"}, {"source_path": "b.md", "chunk_id": "weak"}], [[1, 0], [-1, 0]])
    retriever = Retriever(store, FakeEmbeddings(), top_k=2, min_similarity=0.5)
    assert [item.metadata["chunk_id"] for item in retriever.retrieve("x")] == ["strong"]
    assert retriever.retrieve("  ") == []


def test_retrieval_overfetches_and_diversifies_sources_for_podcast_query():
    class RecordingStore(MemoryStore):
        requested_k = None
        def query(self, embedding, top_k):
            self.requested_k = top_k
            return super().query(embedding, top_k)

    store = RecordingStore()
    metadata = [
        {"source_path": "podcasts/a.md", "chunk_id": "a1", "document_type": "podcast"},
        {"source_path": "podcasts/a.md", "chunk_id": "a2", "document_type": "podcast"},
        {"source_path": "podcasts/a.md", "chunk_id": "a3", "document_type": "podcast"},
        {"source_path": "podcasts/b.md", "chunk_id": "b1", "document_type": "podcast"},
        {"source_path": "newsletters/c.md", "chunk_id": "c1", "document_type": "newsletter"},
    ]
    store.upsert([str(i) for i in range(5)], [f"growth evidence {i}" for i in range(5)], metadata, [[1.0, 1.0]] * 5)
    retriever = Retriever(store, FakeEmbeddings(), top_k=3, min_similarity=.5)

    passages = retriever.retrieve("growth lessons from podcast transcripts")

    assert store.requested_k == 24
    assert [item.metadata["chunk_id"] for item in passages] == ["a1", "b1"]
    assert all(item.metadata["document_type"] == "podcast" for item in passages)


def test_growth_retrieval_seeds_context_with_distinct_focused_evidence():
    class TopicEmbeddings:
        def embed(self, texts):
            vectors = []
            for text in texts:
                if text.startswith("What are the key lessons"):
                    vectors.append([1, 0, 0, 0])
                elif "new-user aha moment" in text:
                    vectors.append([0, 1, 0, 0])
                elif "early product activation" in text:
                    vectors.append([0, 0, 1, 0])
                else:
                    vectors.append([0, 0, 0, 1])
            return vectors

    store = MemoryStore()
    metadata = [
        {"source_path": f"podcasts/{name}.md", "chunk_id": name, "document_type": "podcast"}
        for name in ("generic", "broad", "activation", "word_of_mouth")
    ]
    store.upsert(
        ["generic", "broad", "activation", "word_of_mouth"],
        ["generic growth evidence", "broad growth evidence", "activation evidence", "word of mouth evidence"],
        metadata,
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    )
    retriever = Retriever(store, TopicEmbeddings(), top_k=5, min_similarity=.25)

    passages = retriever.retrieve("What are the key lessons about product growth from podcast transcripts?")

    assert [passage.metadata["chunk_id"] for passage in passages[:3]] == ["broad", "activation", "word_of_mouth"]
    assert all(passage.metadata["source_path"].endswith(".md") for passage in passages)


def test_retrieval_reports_changed_embedding_dimension_before_vector_query():
    class MismatchedEmbeddings:
        def embed(self, _texts):
            return [[1.0, 0.0, 0.0]]
    store = MemoryStore()
    store.upsert(["stored"], ["existing passage"], [{"source_path": "a.md", "chunk_id": "stored"}], [[1.0, 0.0]])
    with pytest.raises(RuntimeError, match="does not match indexed vectors"):
        Retriever(store, MismatchedEmbeddings()).retrieve("query")


def test_rag_generates_only_with_evidence_and_returns_sources():
    store = MemoryStore()
    metadata = {"source_path": "podcasts/guest.md", "chunk_id": "chunk-1", "title": "Episode", "document_type": "podcast", "post_url": "https://example.test/episode"}
    store.upsert(["chunk-1"], ["Evidence about product decisions."], [metadata], [[1.0, 1.0]])
    llm = FakeLLM()
    service = RAGService(Retriever(store, FakeEmbeddings(), top_k=1, min_similarity=.5), llm)
    answer = service.answer("product decisions")
    assert answer.grounded is True
    assert answer.answer == "The indexed passage says this. [S1]"
    assert answer.sources[0].source_id == "S1"
    assert answer.sources[0].url == "https://example.test/episode"
    assert '<source id="S1"' in llm.calls[0][1]
    assert "up to three distinct, concise one-sentence bullets" in llm.calls[0][0]


def test_rag_limits_context_to_three_sources_for_bounded_local_generation():
    store = MemoryStore()
    ids = [f"chunk-{i}" for i in range(5)]
    metadata = [
        {"source_path": f"podcasts/{i}.md", "chunk_id": chunk_id, "title": str(i), "document_type": "podcast"}
        for i, chunk_id in enumerate(ids)
    ]
    store.upsert(ids, [f"Evidence passage {i}." for i in range(5)], metadata, [[1.0, 1.0]] * 5)
    llm = FakeLLM()

    answer = RAGService(Retriever(store, FakeEmbeddings(), top_k=5, min_similarity=.5), llm).answer("growth lessons")

    assert llm.calls[0][1].count("<source id=") == 3
    assert answer.grounded is True
    assert len(answer.sources) == 1


def test_rag_bounds_passage_context_without_changing_source_mapping():
    store = MemoryStore()
    metadata = {"source_path": "podcasts/guest.md", "chunk_id": "chunk-1", "title": "Episode", "document_type": "podcast"}
    store.upsert(["chunk-1"], ["Relevant evidence. " + ("extra context " * 100) + "TAIL_ONLY"], [metadata], [[1.0, 1.0]])
    llm = FakeLLM()

    answer = RAGService(Retriever(store, FakeEmbeddings(), top_k=1, min_similarity=.5), llm).answer("growth")

    assert answer.grounded is True
    assert answer.sources[0].chunk_id == "chunk-1"
    assert "TAIL_ONLY" not in llm.calls[0][1]
    assert '<source id="S1"' in llm.calls[0][1]


def test_rag_generation_failure_logs_stage_and_elapsed_time_without_prompt(caplog):
    import json
    import logging

    class FailingLLM:
        def generate(self, _system, _user):
            try:
                raise TimeoutError("timed out")
            except TimeoutError as cause:
                raise RuntimeError("LLM provider request failed: timed out") from cause

    store = MemoryStore()
    metadata = {"source_path": "podcasts/guest.md", "chunk_id": "chunk-1", "title": "Episode", "document_type": "podcast"}
    store.upsert(["chunk-1"], ["Private transcript passage"], [metadata], [[1.0, 1.0]])
    service = RAGService(Retriever(store, FakeEmbeddings(), top_k=1, min_similarity=.5), FailingLLM())
    with caplog.at_level(logging.ERROR, logger="app.services.rag"):
        with pytest.raises(RuntimeError, match="timed out"):
            service.answer("private user question")

    from app.core.logging_config import JsonFormatter
    failure = next(record for record in caplog.records if getattr(record, "event", None) == "rag_stage_failed")
    payload = json.loads(JsonFormatter().format(failure))
    assert payload["stage"] == "generate"
    assert payload["stage_elapsed_ms"] >= 0
    assert payload["exceptions"][0]["message"] == "LLM provider request failed: timed out"
    assert payload["exceptions"][1]["type"] == "TimeoutError"
    assert payload["exceptions"][1]["message"] == "timed out"
    assert "Private transcript passage" not in json.dumps(payload)
    assert "private user question" not in json.dumps(payload)


def test_empty_retrieval_returns_no_citations_or_llm_call():
    store, llm = MemoryStore(), FakeLLM()
    answer = RAGService(Retriever(store, FakeEmbeddings()), llm).answer("unmatched query")
    assert answer.answer == INSUFFICIENT_EVIDENCE
    assert answer.grounded is False
    assert answer.sources == []
    assert llm.calls == []


def test_unknown_cited_sentence_is_removed_without_discarding_valid_claim():
    store = MemoryStore()
    metadata = {"source_path": "podcasts/guest.md", "chunk_id": "chunk-1", "title": "Episode", "document_type": "podcast"}
    store.upsert(["chunk-1"], ["Evidence passage."], [metadata], [[1.0, 1.0]])
    llm = FakeLLM()
    llm.generate = lambda _system, _user: "Supported claim [S1]. Unsupported citation [S9]."
    answer = RAGService(Retriever(store, FakeEmbeddings(), min_similarity=.5), llm).answer("question")
    assert answer.answer == "Supported claim [S1]."
    assert answer.grounded is True
    assert [source.source_path for source in answer.sources] == ["podcasts/guest.md"]


def test_untraceable_passage_cannot_shift_a_source_id_to_another_passage():
    from app.rag.retrieval import Passage
    from app.services.rag import _traceable_passages

    untraceable = Passage("untraceable text", {}, .9)
    traceable = Passage("traceable text", {"source_path": "real.md", "chunk_id": "c1", "title": "Real"}, .8)
    pairs = _traceable_passages([untraceable, traceable])
    assert len(pairs) == 1
    assert pairs[0][0].source_path == "real.md"
    assert pairs[0][1].text == "traceable text"


@pytest.mark.parametrize("provider_response", [
    "A factual claim without a citation.",
    "A claim with an unknown citation. [S9]",
])
def test_answer_is_not_grounded_without_valid_citations_on_claims(provider_response):
    class RespondingLLM:
        def generate(self, _system, _user):
            return provider_response

    store = MemoryStore()
    metadata = {"source_path": "podcasts/source.md", "chunk_id": "c1", "title": "Source", "document_type": "podcast"}
    store.upsert(["c1"], ["An indexed passage about growth."], [metadata], [[1.0, 1.0]])
    answer = RAGService(Retriever(store, FakeEmbeddings(), min_similarity=.5), RespondingLLM()).answer("growth")
    assert answer.answer == INSUFFICIENT_EVIDENCE
    assert answer.sources == []
    assert answer.grounded is False


def test_uncited_additions_are_removed_while_cited_claim_is_preserved():
    class RespondingLLM:
        def generate(self, _system, _user):
            return "The passage discusses growth. [S1]\n\nThis guarantees success for every company."

    store = MemoryStore()
    metadata = {"source_path": "podcasts/source.md", "chunk_id": "c1", "title": "Source", "document_type": "podcast"}
    store.upsert(["c1"], ["An indexed passage about growth."], [metadata], [[1.0, 1.0]])
    answer = RAGService(Retriever(store, FakeEmbeddings(), min_similarity=.5), RespondingLLM()).answer("growth")

    assert answer.grounded is True
    assert answer.answer == "The passage discusses growth. [S1]"


def test_only_sources_cited_by_the_answer_are_returned():
    class FirstSourceOnlyLLM:
        def generate(self, _system, _user):
            return "This source supports the claim. [S1]"

    store = MemoryStore()
    metadata = [
        {"source_path": "podcasts/used.md", "chunk_id": "c1", "title": "Used", "document_type": "podcast"},
        {"source_path": "podcasts/unused.md", "chunk_id": "c2", "title": "Unused", "document_type": "podcast"},
    ]
    store.upsert(["c1", "c2"], ["Evidence one", "Uncited evidence two"], metadata, [[1.0, 1.0], [1.0, 1.0]])
    answer = RAGService(Retriever(store, FakeEmbeddings(), top_k=2, min_similarity=.5), FirstSourceOnlyLLM()).answer("growth")
    assert answer.grounded is True
    assert [source.source_path for source in answer.sources] == ["podcasts/used.md"]


def test_plain_source_ids_are_normalized_and_uncited_additions_are_removed():
    class PlainIdLLM:
        def generate(self, _system, _user):
            return (
                "Lesson 1: Define early activation around the day-zero or day-one experience, from S1. "
                "This is guaranteed to improve every product's retention."
            )

    store = MemoryStore()
    metadata = {"source_path": "podcasts/amol-avasare.md", "chunk_id": "c1", "title": "Amol", "document_type": "podcast"}
    store.upsert(["c1"], ["Activation is critical; define it as the day-zero or day-one product experience."], [metadata], [[1.0, 1.0]])
    answer = RAGService(Retriever(store, FakeEmbeddings(), min_similarity=.5), PlainIdLLM()).answer("growth")

    assert answer.grounded is True
    assert answer.answer == "Lesson 1: Define early activation around the day-zero or day-one experience, from [S1]."
    assert [source.source_path for source in answer.sources] == ["podcasts/amol-avasare.md"]


def test_source_references_deduplicate_same_chunk():
    from app.rag.retrieval import Passage
    passage = Passage("text", {"source_path": "one.md", "chunk_id": "c", "title": "One", "document_type": "newsletter"}, .9)
    assert len(source_references([passage, passage])) == 1
