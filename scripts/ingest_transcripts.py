"""Index the configured Markdown dataset into the configured ChromaDB collection."""
import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
backend_path = project_root / "backend"
sys.path.insert(0, str(backend_path if backend_path.is_dir() else project_root))
from app.core.config import get_settings
from app.rag.embeddings import OllamaEmbeddings
from app.rag.indexer import index_corpus
from app.rag.documents import chunk_document, load_documents
from app.rag.vector_store import ChromaVectorStore


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    settings = get_settings()
    parser.add_argument("--path", type=Path, default=settings.transcripts_path, help="Dataset directory (defaults to TRANSCRIPTS_PATH)")
    parser.add_argument("--reindex", action="store_true", help="Clear the collection before indexing all sources")
    parser.add_argument("--validate-only", action="store_true", help="Validate indexed Markdown and chunk count without ChromaDB or Ollama")
    args = parser.parse_args()
    if args.validate_only:
        documents = load_documents(args.path)
        chunks = sum(len(chunk_document(doc, size=settings.chunk_size, overlap=settings.chunk_overlap)) for doc in documents)
        print(f"Validated {len(documents)} Markdown documents ({chunks} chunks) under {args.path.resolve()}.")
        raise SystemExit(0)
    store = ChromaVectorStore(str(settings.chroma_persist_directory), settings.rag_collection_name)
    embedder = OllamaEmbeddings(settings.ollama_base_url, settings.ollama_embedding_model, settings.llm_timeout_seconds)
    count = index_corpus(args.path, store, embedder, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap, reindex=args.reindex, batch_size=settings.embedding_batch_size)
    print(f"Indexed {count} chunks from {args.path.resolve()} into collection {settings.rag_collection_name!r}.")
