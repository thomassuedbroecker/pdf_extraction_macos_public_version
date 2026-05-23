from __future__ import annotations

import pytest

from pdf_manager.core.prompts import (
    format_document_for_prompt,
    format_extraction_result_item,
    render_multi_prompt,
    render_prompt,
)
from pdf_manager.models.pdf_record import PdfRecord

pytestmark = pytest.mark.unit


def test_render_prompt_inserts_pdf_fields_and_text(sample_pdf_records: list[PdfRecord]) -> None:
    template = "File={file_name}\nPages={page_count}\nText={text}\nUnknown={missing}"

    rendered = render_prompt(template, sample_pdf_records[0], "Extracted PDF text")

    assert "File=alpha.pdf" in rendered
    assert "Pages=1" in rendered
    assert "Text=Extracted PDF text" in rendered
    assert "Unknown={missing}" in rendered


def test_render_multi_prompt_inserts_file_count_and_documents(sample_pdf_records: list[PdfRecord]) -> None:
    documents = "\n\n".join(
        [
            format_document_for_prompt(1, sample_pdf_records[0], "First document text"),
            format_document_for_prompt(2, sample_pdf_records[1], "Second document text"),
        ]
    )
    template = "Count={file_count}\nPrimary={file_name}\nDocs={documents}\nTextAlias={text}"

    rendered = render_multi_prompt(template, sample_pdf_records, documents)

    assert "Count=2" in rendered
    assert "Primary=alpha.pdf" in rendered
    assert "--- Document 1 ---" in rendered
    assert "First document text" in rendered
    assert "Second document text" in rendered
    assert "TextAlias=--- Document 1 ---" in rendered


def test_format_extraction_result_item_includes_file_and_result(sample_pdf_records: list[PdfRecord]) -> None:
    rendered = format_extraction_result_item(sample_pdf_records[0], result="Summary for alpha")

    assert "File: alpha.pdf" in rendered
    assert f"Path: {sample_pdf_records[0].full_path}" in rendered
    assert "Status: complete" in rendered
    assert "Summary for alpha" in rendered
