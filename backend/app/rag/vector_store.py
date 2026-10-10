"""Vector store interface and ChromaDB persistent implementation."""
from typing import Any, Protocol


class VectorStore(Protocol):
    def get_records(self, ids: list[str]) -> dict[str, dict[str, Any]]: ...
    def upsert(self, ids: list[str], texts: list[str], metadatas: list[dict[str, Any]], embeddings: list[list[float]]) -> None: ...
    def delete_except(self, ids: set[str]) -> None: ...
    def query(self, embedding: list[float], top_k: int) -> list[dict[str, Any]]: ...
    def clear(self) -> None: ...


class ChromaVectorStore:
    def __init__(self, persist_directory: str, collection_name: str):
        import chromadb

        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            collection_name, metadata={"hnsw:space": "cosine"}
        )

    def record_count(self) -> int:
        return self.collection.count()

    def embedding_dimensions(self) -> int | None:
        """Read one stored vector to detect incompatible embedding model dimensions."""
        records = self.collection.get(limit=1, include=["embeddings"])
        vectors = records.get("embeddings")
        return len(vectors[0]) if vectors is not None and len(vectors) else None

    def upsert(self, ids, texts, metadatas, embeddings) -> None:
        self.collection.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)

    def get_records(self, ids):
        """Return stored text and metadata for requested IDs to validate reuse."""
        records = self.collection.get(ids=ids, include=["documents", "metadatas"])
        return {
            record_id: {"text": text, "metadata": metadata}
            for record_id, text, metadata in zip(records["ids"], records["documents"], records["metadatas"])
        }

    def delete_except(self, ids: set[str]) -> None:
        current = self.collection.get(include=[])["ids"]
        stale = [item for item in current if item not in ids]
        if stale:
            self.collection.delete(ids=stale)

    def query(self, embedding, top_k):
        try:
            result = self.collection.query(query_embeddings=[embedding], n_results=top_k, include=["documents", "metadatas", "distances"])
        except Exception as exc:
            raise RuntimeError("ChromaDB query failed") from exc
        rows = []
        for doc, metadata, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
            rows.append({"text": doc, "metadata": metadata, "similarity": 1.0 - float(distance)})
        return rows

    def clear(self) -> None:
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(self.collection.name, metadata={"hnsw:space": "cosine"})
