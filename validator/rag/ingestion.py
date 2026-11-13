"""Ingestion pipeline: load -> clean -> chunk -> embed -> upsert into Qdrant."""
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path

from langchain_core.documents import Document
from qdrant_client import models

from validator.config import settings
from validator.rag import sparse, vectorstore

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class IngestionError(Exception):
    pass


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"-\n(\w)", r"\1", text)        # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_file(path: Path) -> tuple[list[Document], int]:
    """Return one Document per page (PDF) or per file (others), plus the page count."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:
                raise IngestionError("PDF is password-protected") from e
        docs = []
        for i, page in enumerate(reader.pages, start=1):
            text = _clean(page.extract_text() or "")
            if text:
                docs.append(Document(page_content=text, metadata={"page": i}))
        return docs, len(reader.pages)

    if ext == ".docx":
        import docx

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for table in d.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        text = _clean("\n".join(parts))
        return ([Document(page_content=text, metadata={"page": 1})] if text else []), 1

    if ext in {".txt", ".md"}:
        text = _clean(path.read_text(encoding="utf-8", errors="ignore"))
        return ([Document(page_content=text, metadata={"page": 1})] if text else []), 1

    raise IngestionError(f"Unsupported file type: {ext}")


def split_documents(docs: list[Document]) -> list[Document]:
    # Imported here, not at module level: the langchain_text_splitters package eagerly imports
    # sentence-transformers / transformers / torch when they're installed, which added 12-32 s to
    # every backend startup. Now that cost is paid on the first upload only (or not at all,
    # if the cross-encoder has already loaded torch in the background).
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        add_start_index=True,
    )
    return [c for c in splitter.split_documents(docs) if len(c.page_content.strip()) > 20]


# Gemini's free tier counts EVERY text in a batch as one request, limited to 100 per minute. Sending a
# whole document at once therefore fails for any document over ~100 chunks, however long you wait.
EMBED_BATCH = 90
# Validator change: the free tier also caps TOKENS at 30,000 per minute. 90 number-heavy chunks (statistical
# tables) exceed that in a single batch, which then fails however long you wait. Batches are also cut by an
# estimated token count. Measured with Gemini's token counter (2026-11-05): prose is 4-6 characters per token,
# but statistical tables are ~1 (each digit group is its own token), so the estimate assumes 1 per character.
EMBED_BATCH_TOKENS = 20_000
_RETRY_IN = re.compile(r"retry in ([\d.]+)s", re.I)


def _estimated_tokens(text: str) -> int:
    return len(text) + 1


def batches(texts: list[str]) -> list[tuple[int, list[str]]]:
    """(start index, batch) pairs, each within EMBED_BATCH texts and EMBED_BATCH_TOKENS estimated tokens."""
    out, start, current, tokens = [], 0, [], 0
    for i, text in enumerate(texts):
        t = _estimated_tokens(text)
        if current and (len(current) >= EMBED_BATCH or tokens + t > EMBED_BATCH_TOKENS):
            out.append((start, current))
            start, current, tokens = i, [], 0
        current.append(text)
        tokens += t
    if current:
        out.append((start, current))
    return out


# Validator change: pace from our side. Waiting only after a 429 wasn't enough: a rejected batch still counts
# toward the minute (and the client may retry it at once), so the window never cleared and a 12K-token batch
# failed six times in a row (2026-11-05). Before each batch, wait until the last minute's estimated tokens plus
# this batch fit under the budget.
MINUTE_TOKEN_BUDGET = 25_000
MINUTE_TEXT_BUDGET = 90
_sent: list[tuple[float, int, int]] = []  # (time, estimated tokens, texts) of recent batches, all files


def _wait_for_room(tokens: int, count: int, sleep=time.sleep, clock=time.monotonic) -> None:
    while True:
        now = clock()
        _sent[:] = [s for s in _sent if now - s[0] < 61]
        if not _sent or (sum(s[1] for s in _sent) + tokens <= MINUTE_TOKEN_BUDGET
                         and sum(s[2] for s in _sent) + count <= MINUTE_TEXT_BUDGET):
            return
        sleep(max(0.5, 61 - (now - _sent[0][0])))


def embed_paced(texts: list[str], title: str) -> list[list[float]]:
    """Embed in batches under the per-minute limits; on a rate-limit error, wait a full minute and retry."""
    emb = vectorstore.get_embeddings()
    vectors: list[list[float]] = []
    for start, batch in batches(texts):
        estimate = sum(_estimated_tokens(t) for t in batch)
        for attempt in range(6):
            _wait_for_room(estimate, len(batch))
            _sent.append((time.monotonic(), estimate, len(batch)))
            try:
                vectors += emb.embed_documents(batch, batch_size=EMBED_BATCH, task_type="RETRIEVAL_DOCUMENT",
                                               titles=[title] * len(batch))
                break
            except Exception as e:
                msg = str(e)
                if "PerDay" in msg:
                    # Retrying can't help, and rejected batches still count toward the daily quota.
                    raise IngestionError(
                        "Gemini's daily embedding quota (1,000 texts) is used up; it resets at midnight Pacific "
                        "time. Files ingested so far are kept: run ingest again after the reset.") from e
                if "RESOURCE_EXHAUSTED" not in msg or attempt == 5:
                    raise
                # The minute is spent (failed attempts count too): start a fresh one.
                wait = max(float(_RETRY_IN.search(msg).group(1)) if _RETRY_IN.search(msg) else 0, 62.0)
                log.info("Embedding rate limit hit (chunk %d of %d); waiting %.0fs", start, len(texts), wait)
                _sent.clear()
                time.sleep(wait)
        log.info("Embedded chunks %d-%d of %d", start + 1, start + len(batch), len(texts))
    return vectors


def ingest_file(path: Path, *, user_id: str, doc_id: str, filename: str) -> dict:
    """Index a stored file for a user. Returns {"pages": int, "chunks": int}."""
    pages, page_count = load_file(path)
    if not pages:
        raise IngestionError("No extractable text found (the file may be scanned images).")

    chunks = split_documents(pages)
    texts = [c.page_content for c in chunks]
    vectors = embed_paced(texts, filename)

    points = []
    for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
        metadata = {
            "user_id": user_id,
            "doc_id": doc_id,
            "source": filename,
            "page": chunk.metadata.get("page"),
            "chunk_index": idx,
            "start_index": chunk.metadata.get("start_index"),
        }
        points.append(models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{idx}")),
            vector={vectorstore.DENSE: vector, vectorstore.SPARSE: sparse.document_vector(chunk.page_content)},
            payload={"page_content": chunk.page_content, "metadata": metadata},
        ))

    vectorstore.upsert(points)
    return {"pages": page_count, "chunks": len(points)}
