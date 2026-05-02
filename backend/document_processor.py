"""
document_processor.py
Parse PDF, TXT, and DOCX files into text chunks.
Chunking: ~500 tokens with ~50 token overlap (using word-count approximation).
"""

from __future__ import annotations

import io
import logging
from typing import List

logger = logging.getLogger(__name__)

# Approximate chars-per-token for English text
CHARS_PER_TOKEN = 4
CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
CHUNK_CHARS = CHUNK_TOKENS * CHARS_PER_TOKEN        # 2000 chars
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN     # 200 chars


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_document(file_bytes: bytes, filename: str) -> List[str]:
    """
    Parse *file_bytes* according to *filename* extension and return a list
    of non-empty text chunks suitable for embedding.

    Raises:
        ValueError: if the file extension is not supported.
        RuntimeError: if parsing fails.
    """
    lower = filename.lower()

    if lower.endswith(".pdf"):
        raw_text = _parse_pdf(file_bytes)
    elif lower.endswith(".txt"):
        raw_text = _parse_txt(file_bytes)
    elif lower.endswith(".docx"):
        raw_text = _parse_docx(file_bytes)
    else:
        raise ValueError(
            f"Unsupported file type for '{filename}'. "
            "Supported: .pdf, .txt, .docx"
        )

    chunks = _chunk_text(raw_text)
    logger.info("Parsed '%s' → %d chunks", filename, len(chunks))
    return chunks


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_pdf(file_bytes: bytes) -> str:
    try:
        import pypdf  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed. Run: pip install pypdf") from exc

    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    pages: List[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


def _parse_txt(file_bytes: bytes) -> str:
    # Try UTF-8 first, fall back to latin-1 to avoid hard crashes
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")


def _parse_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is not installed. Run: pip install python-docx"
        ) from exc

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

def _chunk_text(text: str) -> List[str]:
    """
    Split *text* into chunks of approximately CHUNK_CHARS characters with
    OVERLAP_CHARS overlap between consecutive chunks.  Each chunk is trimmed
    and empty chunks are discarded.
    """
    text = text.strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + CHUNK_CHARS, text_len)

        # Try to break on a sentence boundary (. ! ?) within the last 200 chars
        if end < text_len:
            boundary = _find_sentence_boundary(text, end, lookback=200)
            if boundary:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Advance with overlap
        start = max(start + 1, end - OVERLAP_CHARS)

    return chunks


def _find_sentence_boundary(text: str, pos: int, lookback: int = 200) -> int | None:
    """
    Look backwards from *pos* for the last sentence-ending punctuation.
    Returns the index *after* the punctuation, or None if not found.
    """
    search_start = max(0, pos - lookback)
    snippet = text[search_start:pos]
    for punct in (".", "!", "?", "\n\n"):
        idx = snippet.rfind(punct)
        if idx != -1:
            return search_start + idx + len(punct)
    return None
