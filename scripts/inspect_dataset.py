"""Report dataset inventory and metadata without printing transcript content."""
import argparse
import json
from collections import Counter
from pathlib import Path


def inspect(root: Path) -> dict:
    files = [path for path in root.rglob("*") if path.is_file()]
    formats = Counter(path.suffix.lower() or "[no extension]" for path in files)
    index_path = root / "index.json"
    collections = {}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for name, entries in index.items():
            if isinstance(entries, list):
                collections[name] = {
                    "count": len(entries),
                    "sample_metadata": {key: value for key, value in entries[0].items() if key != "filename"} if entries else {},
                }
    return {
        "root": str(root.resolve()),
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "formats": dict(formats),
        "collections": collections,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="lennys-newsletterpodcastdata-main", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.path), indent=2, ensure_ascii=False))
