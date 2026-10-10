"""Loading, cleaning, and deterministic chunking of indexed Markdown sources."""
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Document:
    text: str
    metadata: dict[str, Any]


def clean_markdown(text: str) -> str:
    """Remove YAML front matter and normalize whitespace without losing prose."""
    text = text.lstrip("\ufeff")
    if text.startswith("---\n"):
        _, separator, remainder = text[4:].partition("\n---")
        if separator:
            text = remainder.partition("\n")[2]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_documents(root: Path) -> list[Document]:
    """Load only indexed podcast/newsletter Markdown files; reject unsupported data."""
    root = root.resolve()
    index_path = root / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"Expected dataset index at {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    documents: list[Document] = []
    seen: set[str] = set()
    for collection in ("podcasts", "newsletters"):
        records = index.get(collection, [])
        if not isinstance(records, list):
            raise ValueError(f"Index collection {collection!r} must be a list")
        for record in records:
            rel = record.get("filename")
            if not rel:
                raise ValueError(f"Index entry in {collection} has no filename")
            source = (root / rel).resolve()
            if root not in source.parents:
                raise ValueError(f"Indexed source escapes dataset directory: {rel}")
            if source.suffix.lower() != ".md":
                raise ValueError(f"Unsupported indexed format: {rel}")
            if not source.is_file():
                raise FileNotFoundError(source)
            relative_path = source.relative_to(root).as_posix()
            if relative_path in seen:
                raise ValueError(f"Duplicate indexed source: {relative_path}")
            seen.add(relative_path)
            content = clean_markdown(source.read_text(encoding="utf-8"))
            if not content:
                raise ValueError(f"Indexed Markdown source is empty: {relative_path}")
            metadata = {
                "document_type": "podcast" if collection == "podcasts" else "newsletter",
                "title": str(record.get("title") or source.stem),
                "source_path": relative_path,
            }
            for key in ("date", "post_url", "guest", "description", "subtitle", "word_count"):
                if record.get(key) is not None:
                    metadata[key] = record[key]
            documents.append(Document(content, metadata))
    return documents


def chunk_document(document: Document, *, size: int, overlap: int) -> list[Document]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and overlap must be in [0, size)")
    text = document.text
    chunks: list[Document] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(" ", start, end))
            if boundary > start + size // 2:
                end = boundary
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunk_index = len(chunks)
            source_path = document.metadata["source_path"]
            digest = hashlib.sha256(f"{source_path}\0{chunk_index}\0{chunk_text}".encode("utf-8")).hexdigest()
            metadata = {**document.metadata, "chunk_id": digest, "chunk_index": chunk_index}
            chunks.append(Document(chunk_text, metadata))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks
