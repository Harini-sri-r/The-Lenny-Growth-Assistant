"""Repeatable corpus indexing orchestration."""
import logging
from time import perf_counter
from time import monotonic
from pathlib import Path
from app.rag.documents import chunk_document, load_documents
from app.rag.embeddings import EmbeddingProvider
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

def index_corpus(root: Path, store: VectorStore, embedder: EmbeddingProvider, *, chunk_size: int, chunk_overlap: int, reindex: bool = False, batch_size: int = 8) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    pipeline_started = monotonic()
    stage_started = perf_counter()
    documents = load_documents(root)
    load_elapsed = perf_counter() - stage_started
    stage_started = perf_counter()
    chunks = [chunk for doc in documents for chunk in chunk_document(doc, size=chunk_size, overlap=chunk_overlap)]
    chunk_elapsed = perf_counter() - stage_started
    total = len(chunks)
    batch_count = (total + batch_size - 1) // batch_size
    started = monotonic()
    logger.info(
        "Prepared transcript corpus: documents=%d total_chunks=%d load_seconds=%.2f chunk_seconds=%.2f batch_size=%d total_batches=%d",
        len(documents), total, load_elapsed, chunk_elapsed, batch_size, batch_count,
    )
    if reindex:
        logger.warning("Explicit reindex requested; clearing configured vector collection")
        store.clear()
    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    existing = {} if reindex else store.get_records(ids)
    compatible = set()
    for chunk in chunks:
        chunk_id = chunk.metadata["chunk_id"]
        stored = existing.get(chunk_id)
        expected_metadata = {
            key: value for key, value in chunk.metadata.items()
            if isinstance(value, (str, int, float, bool))
        }
        expected_metadata["chunk_size"] = chunk_size
        expected_metadata["chunk_overlap"] = chunk_overlap
        if (stored and stored.get("text") == chunk.text
                and all(stored.get("metadata", {}).get(key) == value for key, value in expected_metadata.items())):
            compatible.add(chunk_id)

    missing_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_id"] not in compatible]
    missing_total = len(missing_chunks)
    batch_count = (missing_total + batch_size - 1) // batch_size
    logger.info(
        "Incremental transcript scan: reusable_chunks=%d chunks_to_embed=%d incompatible_existing=%d",
        len(compatible), missing_total, len(existing) - len(compatible.intersection(existing)),
    )
    for batch_number, offset in enumerate(range(0, missing_total, batch_size), start=1):
        batch = missing_chunks[offset:offset + batch_size]
        batch_started = monotonic()
        embed_started = perf_counter()
        chunk_end = offset + len(batch)
        logger.info("Embedding batch %d/%d: missing_chunks=%d-%d/%d corpus_chunks=%d", batch_number, batch_count, offset + 1, chunk_end, missing_total, total)
        try:
            vectors = embedder.embed([chunk.text for chunk in batch])
            embed_elapsed = perf_counter() - embed_started
            if len(vectors) != len(batch):
                raise RuntimeError("Embedding provider returned a different number of vectors than inputs")
            metadata = []
            for chunk in batch:
                item = {key: value for key, value in chunk.metadata.items() if isinstance(value, (str, int, float, bool))}
                item["chunk_size"] = chunk_size
                item["chunk_overlap"] = chunk_overlap
                metadata.append(item)
            write_started = perf_counter()
            store.upsert([item["chunk_id"] for item in metadata], [chunk.text for chunk in batch], metadata, vectors)
            write_elapsed = perf_counter() - write_started
        except Exception:
            logger.exception(
                "Transcript indexing failed: batch=%d/%d chunks=%d-%d/%d elapsed_seconds=%.2f total_elapsed_seconds=%.2f",
                batch_number, batch_count, offset + 1, chunk_end, total,
                monotonic() - batch_started, monotonic() - started,
            )
            raise
        logger.info(
            "Completed batch %d/%d: embedded_chunks=%d/%d reusable_chunks=%d corpus_chunks=%d embedding_seconds=%.2f chroma_write_seconds=%.2f embedding_chunks_per_second=%.2f batch_elapsed_seconds=%.2f total_elapsed_seconds=%.2f",
            batch_number, batch_count, chunk_end, missing_total, len(compatible), total, embed_elapsed, write_elapsed,
            len(batch) / embed_elapsed if embed_elapsed else float("inf"),
            monotonic() - batch_started, monotonic() - started,
        )
    stale_started = perf_counter()
    store.delete_except(set(ids))
    cleanup_elapsed = perf_counter() - stale_started
    logger.info(
        "Transcript indexing complete: indexed_chunks=%d reused_chunks=%d total_chunks=%d load_seconds=%.2f chunk_seconds=%.2f stale_cleanup_seconds=%.2f elapsed_seconds=%.2f",
        total, len(compatible), total, load_elapsed, chunk_elapsed, cleanup_elapsed, monotonic() - pipeline_started,
    )
    return len(chunks)
