"""Semantic retrieval with explicit relevance filtering."""
from dataclasses import dataclass
import logging

from app.core.rag_diagnostics import log_rag_diagnostic
from app.rag.embeddings import EmbeddingProvider
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Passage:
    text: str
    metadata: dict
    similarity: float


class Retriever:
    def __init__(self, store: VectorStore, embedder: EmbeddingProvider, *, top_k: int = 5, min_similarity: float = 0.25, per_source_limit: int = 1):
        if top_k < 1 or per_source_limit < 1 or not -1 <= min_similarity <= 1:
            raise ValueError("top_k must be positive and min_similarity must be between -1 and 1")
        self.store, self.embedder, self.top_k, self.min_similarity, self.per_source_limit = store, embedder, top_k, min_similarity, per_source_limit

    def retrieve(self, query: str) -> list[Passage]:
        query = query.strip()
        if not query:
            return []
        try:
            queries = [("question", query)]
            query_lower = query.lower()
            if "growth" in query_lower or "grow" in query_lower:
                queries.append(("growth_focus", 
                    "product growth lessons: improve activation and the new-user aha moment; "
                    "improve engagement and retention; use experimentation, distribution, "
                    "referrals, existing customers, and product-led growth"
                ))
                queries.extend([
                    (
                        "activation_retention",
                        "product growth lesson: define and improve early product activation, "
                        "the aha moment, engagement, and user retention",
                    ),
                    (
                        "word_of_mouth",
                        "product growth lesson: build a remarkable product that users recommend; "
                        "word of mouth, referrals, and growth through existing customers",
                    ),
                ])
            vectors = self.embedder.embed([text for _label, text in queries])
            dimension_reader = getattr(self.store, "embedding_dimensions", None)
            stored_dimensions = dimension_reader() if dimension_reader else None
            ranked: dict[str, tuple[dict, float, int]] = {}
            raw_count = 0
            query_k = min(max(self.top_k * 8, self.top_k), 100)
            variant_matches: list[list[dict]] = []
            query_metrics = []
            for query_index, vector in enumerate(vectors):
                query_weight = 0.25 if query_index == 0 and len(vectors) > 1 else 1.0
                if stored_dimensions is not None and len(vector) != stored_dimensions:
                    raise RuntimeError(
                        f"Query embedding dimension ({len(vector)}) does not match indexed vectors ({stored_dimensions}); "
                        "configure the original embedding model or intentionally rebuild the index"
                    )
                query_matches = self.store.query(vector, query_k)
                raw_count += len(query_matches)
                variant_matches.append(query_matches)
                query_metrics.append({
                    "variant": queries[query_index][0],
                    "result_count": len(query_matches),
                    "top_matches": [
                        {
                            "similarity": round(float(row["similarity"]), 4),
                            "distance": round(1.0 - float(row["similarity"]), 4),
                            "source_path": str(row["metadata"].get("source_path") or "")[:240],
                            "document_type": str(row["metadata"].get("document_type") or "")[:40],
                        }
                        for row in query_matches[:10]
                    ],
                })
                for rank, row in enumerate(query_matches, 1):
                    key = str(row["metadata"].get("chunk_id") or row.get("text", ""))
                    old = ranked.get(key)
                    rrf_score = query_weight / (60 + rank) + (old[1] if old else 0.0)
                    max_similarity = max(row["similarity"], old[0]["similarity"] if old else -1.0)
                    ranked[key] = (dict(row, similarity=max_similarity), rrf_score, rank)
        except Exception as exc:
            log_rag_diagnostic(logger, "rag_retrieval_failed", retriever_id=id(self), error_type=type(exc).__name__)
            raise
        ordered = sorted(ranked.values(), key=lambda item: item[1], reverse=True)
        eligible = {
            str(row["metadata"].get("chunk_id") or row.get("text", "")): Passage(row["text"], row["metadata"], row["similarity"])
            for row, _score, _rank in ordered
            if row["similarity"] >= self.min_similarity
        }
        candidates = [
            eligible[str(row["metadata"].get("chunk_id") or row.get("text", ""))]
            for row, _score, _rank in ordered
            if str(row["metadata"].get("chunk_id") or row.get("text", "")) in eligible
        ]
        podcast_only = "podcast" in query.lower() or "podcasts" in query.lower() or "episode" in query.lower() or "episodes" in query.lower()
        counts: dict[str, int] = {}
        passages = []
        selected_chunks: set[str] = set()
        podcast_filtered_count = 0
        duplicate_source_count = 0

        def try_retain(passage: Passage) -> bool:
            nonlocal podcast_filtered_count, duplicate_source_count
            if podcast_only and passage.metadata.get("document_type") != "podcast":
                podcast_filtered_count += 1
                return False
            source = str(passage.metadata.get("source_path") or passage.metadata.get("chunk_id") or "")
            if not source or counts.get(source, 0) >= self.per_source_limit:
                duplicate_source_count += 1
                return False
            passages.append(passage)
            counts[source] = counts.get(source, 0) + 1
            selected_chunks.add(str(passage.metadata.get("chunk_id") or passage.text))
            return True

        # A broad growth query can match several unrelated growth subtopics.
        # Seed the bounded context with the best podcast passage for each
        # focused variant before filling remaining slots by fused rank.
        for matches in variant_matches[1:]:
            for row in matches:
                key = str(row["metadata"].get("chunk_id") or row.get("text", ""))
                passage = eligible.get(key)
                if passage is None:
                    continue
                before = len(passages)
                if try_retain(passage):
                    break
                if len(passages) > before:
                    break

        for passage in candidates:
            key = str(passage.metadata.get("chunk_id") or passage.text)
            if key in selected_chunks:
                continue
            try_retain(passage)
            if len(passages) == self.top_k:
                break
        log_rag_diagnostic(
            logger, "rag_retrieval_complete", retriever_id=id(self), raw_count=raw_count,
            filtered_count=len(passages), top_k=self.top_k, query_variant_count=len(query_metrics),
            query_metrics=query_metrics, candidate_count=len(ranked), threshold_count=len(candidates),
            podcast_filtered_count=podcast_filtered_count, duplicate_source_count=duplicate_source_count,
            retained_passages=[
                {
                    "similarity": round(float(p.similarity), 4),
                    "source_path": str(p.metadata.get("source_path") or "")[:240],
                    "chunk_id": str(p.metadata.get("chunk_id") or "")[:80],
                    "document_type": str(p.metadata.get("document_type") or "")[:40],
                }
                for p in passages
            ],
            podcast_only=podcast_only, similarity_threshold=self.min_similarity,
        )
        return passages
