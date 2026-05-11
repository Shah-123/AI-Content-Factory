"""
document_ingest.py — Parse user-uploaded documents (PDF / DOCX / TXT / MD)
and turn them into `EvidenceItem`s that the existing orchestrator + workers
can cite.

Public surface:
    parse_document(path)            -> {"text", "pages", "metadata"}
    chunk_text(pages, ...)          -> List[Chunk]
    extract_evidence_from_chunks(...) -> List[EvidenceItem]
    derive_topic_from_document(text)-> str
    document_ingest_node(state)     -> dict   (LangGraph node)

The pipeline writes an `evidence.json` file to `uploads/<upload_id>/` at
upload time so the LangGraph node only needs to load it (no re-parsing,
no re-LLM-extraction during the actual job run).
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from Graph.state import EvidenceItem, EvidencePack, State
from Graph.templates import RESEARCH_SYSTEM

from .utils import _emit, _job, llm, logger


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Hard cap on how many chunks we'll send to the LLM for a single document.
# Keeps cost predictable on a 200-page PDF.
_MAX_CHUNKS = 30

# Default chunking parameters (in characters, not tokens).
# ~6000 chars ≈ 1.5k tokens — comfortable for a single LLM extraction call.
_DEFAULT_CHUNK_CHARS = 6000
_DEFAULT_OVERLAP = 400

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """A contiguous slice of document text plus the page range it spans."""

    text: str
    page_start: int
    page_end: int


# ---------------------------------------------------------------------------
# 1. PARSING
# ---------------------------------------------------------------------------


def _parse_pdf(path: Path) -> dict:
    """Extract per-page text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError(
            "pypdf is required to parse PDF files. Install with `pip install pypdf`."
        ) from e

    reader = PdfReader(str(path))
    pages: List[str] = []
    for page in reader.pages:
        try:
            pages.append((page.extract_text() or "").strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PDF page extraction failed: {exc}")
            pages.append("")

    text = "\n\n".join(p for p in pages if p)
    return {
        "text": text,
        "pages": pages,
        "metadata": {"format": "pdf", "page_count": len(pages)},
    }


def _parse_docx(path: Path) -> dict:
    """Extract paragraph text from a DOCX. We treat each Heading-1 block
    as a logical 'page' for citation purposes."""
    try:
        import docx  # python-docx
    except ImportError as e:
        raise RuntimeError(
            "python-docx is required to parse DOCX files."
        ) from e

    document = docx.Document(str(path))
    pages: List[str] = []
    buffer: List[str] = []

    for para in document.paragraphs:
        style_name = (para.style.name or "").lower() if para.style else ""
        if style_name.startswith("heading 1") and buffer:
            pages.append("\n".join(buffer).strip())
            buffer = []
        if para.text:
            buffer.append(para.text)

    if buffer:
        pages.append("\n".join(buffer).strip())

    # Fallback: if the doc had no Heading-1 sections, treat the whole thing
    # as a single page.
    if not pages:
        pages = ["\n".join(p.text for p in document.paragraphs if p.text).strip()]

    text = "\n\n".join(p for p in pages if p)
    return {
        "text": text,
        "pages": pages,
        "metadata": {"format": "docx", "page_count": len(pages)},
    }


def _parse_text(path: Path, fmt: str) -> dict:
    """Read a plain text or markdown file."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Split on form-feeds (rare) or huge blank gaps, otherwise treat as one page.
    parts = raw.split("\f")
    pages = [p.strip() for p in parts if p.strip()] or [raw.strip()]
    return {
        "text": raw.strip(),
        "pages": pages,
        "metadata": {"format": fmt, "page_count": len(pages)},
    }


def parse_document(path: str | Path) -> dict:
    """Dispatch to the right parser based on file extension.

    Returns a dict shaped:
        {"text": str, "pages": List[str], "metadata": {...}}
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Upload not found: {p}")

    ext = p.suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(p)
    if ext == ".docx":
        return _parse_docx(p)
    if ext == ".txt":
        return _parse_text(p, "txt")
    if ext == ".md":
        return _parse_text(p, "md")

    raise ValueError(
        f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTS)}"
    )


# ---------------------------------------------------------------------------
# 2. CHUNKING
# ---------------------------------------------------------------------------


def chunk_text(
    pages: List[str],
    max_chars: int = _DEFAULT_CHUNK_CHARS,
    overlap: int = _DEFAULT_OVERLAP,
) -> List[Chunk]:
    """Greedy chunker that respects page boundaries.

    Pages are concatenated until adding the next page would exceed
    `max_chars`. When a single page is larger than `max_chars`, that page
    is split into multiple chunks of `max_chars - overlap` step.
    """
    chunks: List[Chunk] = []
    if not pages:
        return chunks

    buf = ""
    buf_start_page = 0
    last_page_in_buf = 0

    for page_idx, page in enumerate(pages):
        page = page or ""

        # If a single page is gigantic, hard-split it.
        if len(page) > max_chars:
            # Flush current buffer first.
            if buf:
                chunks.append(Chunk(buf.strip(), buf_start_page + 1, last_page_in_buf + 1))
                buf = ""

            step = max(1, max_chars - overlap)
            for i in range(0, len(page), step):
                segment = page[i : i + max_chars]
                if not segment.strip():
                    continue
                chunks.append(Chunk(segment.strip(), page_idx + 1, page_idx + 1))
            buf_start_page = page_idx
            last_page_in_buf = page_idx
            continue

        # Normal flow: try to extend buffer.
        if not buf:
            buf = page
            buf_start_page = page_idx
            last_page_in_buf = page_idx
            continue

        if len(buf) + 2 + len(page) <= max_chars:
            buf = f"{buf}\n\n{page}"
            last_page_in_buf = page_idx
        else:
            chunks.append(Chunk(buf.strip(), buf_start_page + 1, last_page_in_buf + 1))
            buf = page
            buf_start_page = page_idx
            last_page_in_buf = page_idx

    if buf.strip():
        chunks.append(Chunk(buf.strip(), buf_start_page + 1, last_page_in_buf + 1))

    return chunks


# ---------------------------------------------------------------------------
# 3. EVIDENCE EXTRACTION
# ---------------------------------------------------------------------------


def _extract_one_chunk(chunk: Chunk, filename: str, topic_hint: str) -> List[EvidenceItem]:
    """Send a single chunk to the LLM and return EvidenceItems."""
    extractor = llm.with_structured_output(EvidencePack)

    span = (
        f"page {chunk.page_start}"
        if chunk.page_start == chunk.page_end
        else f"pages {chunk.page_start}-{chunk.page_end}"
    )

    prompt = (
        f"Source document: {filename} ({span})\n"
        f"Working topic: {topic_hint or 'N/A'}\n\n"
        f"Read the following excerpt and extract 3-6 hard, verifiable facts, "
        f"statistics, or specific claims that a writer could cite verbatim. "
        f"Each fact must be self-contained and quotable — no opinions or filler.\n\n"
        f"EXCERPT:\n{chunk.text}"
    )

    try:
        pack = extractor.invoke(
            [
                SystemMessage(content=RESEARCH_SYSTEM),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Doc-evidence extraction failed for {filename} {span}: {exc}")
        return []

    cite_url = f"file://{filename}#p{chunk.page_start}"
    items: List[EvidenceItem] = []
    for ev in pack.evidence:
        items.append(
            EvidenceItem(
                title=ev.title or f"{filename} ({span})",
                url=cite_url,
                snippet=ev.snippet,
                published_at=ev.published_at,
                source=filename,
                authors=ev.authors,
            )
        )
    return items


def extract_evidence_from_chunks(
    chunks: List[Chunk],
    filename: str,
    topic_hint: str = "",
    max_chunks: int = _MAX_CHUNKS,
) -> tuple[List[EvidenceItem], bool]:
    """Run LLM extraction in parallel across chunks.

    Returns (evidence_items, was_truncated). Caps at `max_chunks` to keep
    costs predictable on long documents.
    """
    if not chunks:
        return [], False

    truncated = len(chunks) > max_chunks
    work = chunks[:max_chunks]

    out: List[EvidenceItem] = []
    if not work:
        return out, truncated

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_extract_one_chunk, c, filename, topic_hint): c for c in work
        }
        for fut in as_completed(futures):
            try:
                out.extend(fut.result() or [])
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Chunk extractor raised: {exc}")

    # De-duplicate by snippet (LLM occasionally repeats stats across chunks).
    seen: set[str] = set()
    deduped: List[EvidenceItem] = []
    for item in out:
        key = (item.snippet or "").strip().lower()[:160]
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped, truncated


# ---------------------------------------------------------------------------
# 4. TOPIC DERIVATION (used only when source_mode == "auto_topic")
# ---------------------------------------------------------------------------


def derive_topic_from_document(text: str) -> str:
    """Return a 6-10 word working title derived from the document body."""
    excerpt = (text or "").strip()
    if not excerpt:
        return ""
    excerpt = excerpt[:6000]

    try:
        resp = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You write short, SEO-friendly working titles. "
                        "Read the document excerpt and return ONE line of 6-10 words "
                        "that captures its core subject. No quotes, no punctuation at the end."
                    )
                ),
                HumanMessage(content=f"DOCUMENT EXCERPT:\n{excerpt}"),
            ]
        )
        title = (resp.content or "").strip().splitlines()[0].strip(" \"'.")
        return title[:120]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"derive_topic_from_document failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# 5. UPLOAD HELPER (used by api.py at upload time)
# ---------------------------------------------------------------------------


def ingest_upload(upload_dir: Path, original_filename: str) -> dict:
    """End-to-end upload processing: parse → chunk → extract → persist.

    Writes `evidence.json` and `meta.json` next to the source file so the
    pipeline can load them later without re-running the LLM extraction.
    Returns a metadata dict suitable for the HTTP response.
    """
    src_files = [
        p for p in upload_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]
    if not src_files:
        raise FileNotFoundError(f"No supported source file in {upload_dir}")
    src = src_files[0]

    parsed = parse_document(src)
    chunks = chunk_text(parsed["pages"])
    evidence, truncated = extract_evidence_from_chunks(
        chunks, original_filename, topic_hint=""
    )
    derived_topic = derive_topic_from_document(parsed["text"])

    # Persist evidence so document_ingest_node can load it cheaply.
    evidence_path = upload_dir / "evidence.json"
    with evidence_path.open("w", encoding="utf-8") as f:
        json.dump([e.model_dump() for e in evidence], f, indent=2)

    preview = (parsed["text"] or "")[:600]

    meta = {
        "filename": original_filename,
        "stored_path": str(src),
        "format": parsed["metadata"].get("format"),
        "pages": parsed["metadata"].get("page_count", 0),
        "chunks": len(chunks),
        "chunks_processed": min(len(chunks), _MAX_CHUNKS),
        "evidence_count": len(evidence),
        "truncated": truncated,
        "derived_topic": derived_topic,
        "preview": preview,
    }
    with (upload_dir / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return meta


def load_upload_metadata(upload_dir: Path) -> Optional[dict]:
    meta_file = upload_dir / "meta.json"
    if not meta_file.exists():
        return None
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read upload meta {meta_file}: {exc}")
        return None


def load_upload_evidence(upload_dir: Path) -> List[EvidenceItem]:
    ev_file = upload_dir / "evidence.json"
    if not ev_file.exists():
        return []
    try:
        raw = json.loads(ev_file.read_text(encoding="utf-8"))
        return [EvidenceItem(**item) for item in raw]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to load doc evidence {ev_file}: {exc}")
        return []


# ---------------------------------------------------------------------------
# 6. PIPELINE NODE
# ---------------------------------------------------------------------------


def _resolve_uploads_root() -> Path:
    """Same root that api.py uses (Agents_backend/uploads/)."""
    here = Path(__file__).resolve()
    # …/Agents_backend/Graph/agents/document_ingest.py → up 3 = Agents_backend
    backend_dir = here.parents[2]
    root = backend_dir / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def document_ingest_node(state: State) -> dict:
    """LangGraph node: load doc evidence + (optionally) derive topic.

    Runs only when `state["upload_id"]` is set. Reads pre-computed
    `evidence.json` written by the upload endpoint. If `source_mode` is
    "auto_topic" and the user did not supply a topic, the derived topic
    is promoted into state.
    """
    job_id = _job(state)
    upload_id = state.get("upload_id") or ""
    source_mode = state.get("source_mode") or "hybrid"

    if not upload_id:
        # Defensive: shouldn't be routed here unless an upload exists.
        return {}

    _emit(job_id, "ingest", "started",
          "Loading document evidence...",
          {"upload_id": upload_id, "source_mode": source_mode})
    logger.info(f"📄 INGEST --- upload_id={upload_id} mode={source_mode}")

    upload_dir = _resolve_uploads_root() / upload_id
    if not upload_dir.exists():
        _emit(job_id, "ingest", "error", f"Upload {upload_id} not found.")
        return {}

    meta = load_upload_metadata(upload_dir) or {}
    evidence = load_upload_evidence(upload_dir)

    out: dict = {
        "evidence": evidence,
        "document_filename": meta.get("filename"),
    }

    # Topic auto-derivation
    if source_mode == "auto_topic":
        derived = (meta.get("derived_topic") or "").strip()
        topic = (state.get("topic") or "").strip()
        if derived and not topic:
            out["topic"] = derived

    _emit(
        job_id, "ingest", "completed",
        f"Loaded {len(evidence)} evidence item(s) from {meta.get('filename', 'document')}",
        {
            "evidence_count": len(evidence),
            "pages": meta.get("pages", 0),
            "chunks": meta.get("chunks", 0),
            "truncated": meta.get("truncated", False),
        },
    )
    logger.info(f"✅ Ingest complete: {len(evidence)} evidence item(s)")
    return out
