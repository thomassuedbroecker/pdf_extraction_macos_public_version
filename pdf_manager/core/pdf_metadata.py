"""PDF metadata extraction with pypdf."""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader

from pdf_manager.models.pdf_record import PdfRecord

LOGGER = logging.getLogger(__name__)
PREVIEW_LIMIT = 800


def _metadata_value(metadata: object, key: str) -> str | None:
    value = getattr(metadata, key, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_pdf_metadata(path: Path, include_text_preview: bool = True) -> PdfRecord:
    """Extract filesystem and PDF metadata for one file.

    Bad, encrypted, or unreadable PDFs are represented as records with an error
    field instead of raising exceptions to callers.
    """
    try:
        record = PdfRecord.from_path(path)
    except OSError as exc:
        LOGGER.exception("Could not read filesystem metadata for %s", path)
        return PdfRecord(
            file_name=path.name,
            full_path=str(path),
            parent_folder=str(path.parent),
            file_size_bytes=0,
            created_date=None,
            modified_date=None,
            error=str(exc),
        )

    try:
        reader = PdfReader(str(path))
        record.encrypted = bool(reader.is_encrypted)

        if reader.is_encrypted:
            # pypdf returns 0 when an empty password does not decrypt the file.
            if reader.decrypt("") == 0:
                record.text_extractable = False
                record.error = "PDF is encrypted and cannot be opened with an empty password"
                return record

        record.page_count = len(reader.pages)
        metadata = reader.metadata
        if metadata:
            record.title = _metadata_value(metadata, "title")
            record.author = _metadata_value(metadata, "author")
            record.subject = _metadata_value(metadata, "subject")
            record.producer = _metadata_value(metadata, "producer")

        if include_text_preview and record.page_count:
            try:
                text = reader.pages[0].extract_text() or ""
                normalized = " ".join(text.split())
                record.text_extractable = bool(normalized)
                record.text_preview = normalized[:PREVIEW_LIMIT] or None
            except Exception as exc:  # pypdf can raise parser-specific exceptions.
                LOGGER.info("Text extraction failed for %s: %s", path, exc)
                record.text_extractable = False
                record.error = f"Text extraction failed: {exc}"
        else:
            record.text_extractable = False
    except Exception as exc:
        LOGGER.exception("PDF metadata extraction failed for %s", path)
        record.error = f"PDF read failed: {exc}"
        if record.encrypted is None:
            record.encrypted = False
        if record.text_extractable is None:
            record.text_extractable = False

    return record
