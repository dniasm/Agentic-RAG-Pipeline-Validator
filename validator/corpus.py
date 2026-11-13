"""The corpus: files in data/corpus, ingested with day7's pipeline (load -> clean -> chunk -> embed -> Qdrant).

A manifest (data/state/corpus.json) remembers what was ingested, so unchanged files are skipped and a changed
file is re-ingested. Gemini's free tier counts every chunk as one embedding request (1,000 a day), so
`plan()` estimates the chunk count before anything is sent.
"""
import json
import logging
import threading
from pathlib import Path

from validator.config import settings
from validator.rag import ingestion, retrieval, vectorstore

log = logging.getLogger(__name__)

MANIFEST = Path(settings.database_path).parent / "corpus.json"
_lock = threading.Lock()


def _read_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _write_manifest(data: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, indent=2), encoding="utf-8")


def corpus_files() -> list[Path]:
    root = Path(settings.corpus_dir)
    root.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in ingestion.SUPPORTED_EXTENSIONS)


def _name(path: Path) -> str:
    return path.relative_to(settings.corpus_dir).as_posix()


def status() -> dict:
    """Every corpus file with its state: ingested, changed (needs re-ingesting) or new."""
    manifest = _read_manifest()
    files = []
    for path in corpus_files():
        name, sha = _name(path), ingestion.file_sha256(path.read_bytes())
        entry = manifest.get(name)
        state = "new" if not entry else ("ingested" if entry["sha256"] == sha else "changed")
        files.append({"name": name, "size_kb": round(path.stat().st_size / 1024, 1), "state": state,
                      "chunks": entry.get("chunks") if entry else None, "pages": entry.get("pages") if entry else None})
    removed = [n for n in manifest if n not in {f["name"] for f in files}]
    try:
        stored = vectorstore.count_user_vectors(settings.corpus_owner)
    except Exception as e:  # noqa: BLE001 - shown in the UI
        stored = None
        log.warning("Could not count stored chunks: %s", e)
    return {"files": files, "removed": removed, "stored_chunks": stored,
            "ingested_chunks": sum(e.get("chunks", 0) for e in manifest.values())}


def plan() -> dict:
    """Chunk counts for files that still need ingesting (no embedding requests are sent)."""
    todo = []
    for f in status()["files"]:
        if f["state"] == "ingested":
            continue
        pages, _ = ingestion.load_file(Path(settings.corpus_dir) / f["name"])
        todo.append({"name": f["name"], "chunks": len(ingestion.split_documents(pages))})
    total = sum(t["chunks"] for t in todo)
    return {"files": todo, "chunks": total,
            "note": "Each chunk is one Gemini embedding request (free tier: 1,000 a day, shared with searches)."}


def ingest(progress=lambda msg: None) -> dict:
    """Ingest new and changed files, and drop files that were removed from the folder."""
    with _lock:
        manifest = _read_manifest()
        current = {_name(p): p for p in corpus_files()}
        for name in [n for n in manifest if n not in current]:
            vectorstore.delete_document_vectors(settings.corpus_owner, manifest[name]["doc_id"])
            del manifest[name]
            progress(f"Removed {name}")
        done = []
        for name, path in current.items():
            sha = ingestion.file_sha256(path.read_bytes())
            entry = manifest.get(name)
            if entry and entry["sha256"] == sha:
                continue
            if entry:
                vectorstore.delete_document_vectors(settings.corpus_owner, entry["doc_id"])
            doc_id = sha[:16]
            progress(f"Ingesting {name}")
            result = ingestion.ingest_file(path, user_id=settings.corpus_owner, doc_id=doc_id, filename=name)
            manifest[name] = {"sha256": sha, "doc_id": doc_id, **result}
            _write_manifest(manifest)  # saved after each file, so an interrupted ingest resumes
            done.append({"name": name, **result})
            progress(f"Ingested {name}: {result['chunks']} chunks")
        _write_manifest(manifest)
        return {"ingested": done, "total_chunks": sum(e["chunks"] for e in manifest.values())}


def search(query: str, limit: int) -> list[dict]:
    """Hybrid search over the whole corpus (dense + BM25, fused with RRF), as the judges use it.
    No reranker: the judge reads the passages and decides what they show."""
    hits = retrieval.retrieve([query], settings.corpus_owner, k=max(limit - 2, 1), min_score=0.0)
    return hits[:limit]


def read_text(name: str) -> str:
    """The full extracted text of one corpus file (used when writing the question set)."""
    pages, _ = ingestion.load_file(Path(settings.corpus_dir) / name)
    return "\n\n".join(p.page_content for p in pages)
