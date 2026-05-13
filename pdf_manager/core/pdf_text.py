"""Full text extraction helpers for optional local LLM workflows."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

DEFAULT_TEXT_LIMIT = 60_000


def extract_pdf_text(path: str | Path, max_chars: int = DEFAULT_TEXT_LIMIT) -> str:
    """Extract best-effort text from a PDF, capped for local LLM prompts."""
    reader = PdfReader(str(path))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("PDF is encrypted and cannot be opened with an empty password")

    chunks: list[str] = []
    remaining = max_chars
    for page in reader.pages:
        if remaining <= 0:
            break
        text = page.extract_text() or ""
        normalized = " ".join(text.split())
        if not normalized:
            continue
        chunks.append(normalized[:remaining])
        remaining -= len(chunks[-1])
    return "\n\n".join(chunks)
