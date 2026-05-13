"""Prompt template helpers for local extraction workflows."""

from __future__ import annotations

from pdf_manager.models.pdf_record import PdfRecord

DEFAULT_EXTRACTION_PROMPT = """You are extracting useful information from a local PDF.

Return a concise, structured result with:
- title or topic
- short summary
- key entities
- important dates or amounts
- action items or decisions
- uncertainty notes if the text is incomplete

File: {file_name}
Path: {full_path}
Pages: {page_count}

PDF text:
{text}
"""


def render_prompt(template: str, record: PdfRecord, text: str) -> str:
    """Render a prompt template with PDF record fields and extracted text."""
    values = record.to_dict()
    values["text"] = text
    values["documents"] = text
    values["file_count"] = 1
    return template.format_map(_SafeFormatDict(values))


def render_multi_prompt(template: str, records: list[PdfRecord], documents: str) -> str:
    """Render a prompt template for one or more selected PDF records."""
    values = records[0].to_dict() if records else {}
    values["file_count"] = len(records)
    values["documents"] = documents
    values["text"] = documents
    return template.format_map(_SafeFormatDict(values))


def format_document_for_prompt(
    index: int,
    record: PdfRecord,
    text: str,
    extraction_error: str | None = None,
) -> str:
    """Format one PDF's metadata and extracted text for a multi-file prompt."""
    lines = [
        f"--- Document {index} ---",
        f"File: {record.file_name}",
        f"Path: {record.full_path}",
        f"Pages: {record.page_count if record.page_count is not None else 'unknown'}",
    ]
    if record.title:
        lines.append(f"Title: {record.title}")
    if record.author:
        lines.append(f"Author: {record.author}")
    if record.subject:
        lines.append(f"Subject: {record.subject}")
    if extraction_error:
        lines.append(f"Extraction error: {extraction_error}")
    lines.extend(["Text:", text.strip()])
    return "\n".join(lines)


def format_extraction_result_item(record: PdfRecord, result: str | None = None, error: str | None = None) -> str:
    """Format one file's local extraction outcome for display in the UI."""
    lines = [
        f"File: {record.file_name}",
        f"Path: {record.full_path}",
    ]
    if error:
        lines.extend(["Status: error", "", error.strip()])
    else:
        lines.extend(["Status: complete", "", (result or "Ollama returned an empty response.").strip()])
    return "\n".join(lines)


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
