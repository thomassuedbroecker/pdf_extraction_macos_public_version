from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdf_manager.models.pdf_record import PdfRecord

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def write_sample_pdf(path: Path, title: str = "Sample PDF", text: str | None = None, encrypted: bool = False) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text:
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 220 Td ({text}) Tj ET".encode("utf-8"))
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = font
        resources = DictionaryObject()
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Contents")] = stream
        page[NameObject("/Resources")] = resources
    writer.add_metadata(
        {
            "/Title": title,
            "/Author": "Test Author",
            "/Subject": "Test Subject",
            "/Producer": "pytest",
        }
    )
    if encrypted:
        writer.encrypt("secret")
    with path.open("wb") as handle:
        writer.write(handle)


@pytest.fixture
def sample_pdf_factory():
    return write_sample_pdf


@pytest.fixture
def sample_pdf_folder(tmp_path: Path) -> Path:
    write_sample_pdf(tmp_path / "sample.pdf")
    return tmp_path


@pytest.fixture
def nested_pdf_folder(tmp_path: Path) -> Path:
    nested = tmp_path / "nested"
    nested.mkdir()
    write_sample_pdf(tmp_path / "root.pdf", title="Root")
    write_sample_pdf(nested / "child.pdf", title="Child")
    return tmp_path


@pytest.fixture
def non_pdf_folder(tmp_path: Path) -> Path:
    (tmp_path / "notes.txt").write_text("not a pdf", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"png")
    return tmp_path


@pytest.fixture
def sample_pdf_records(tmp_path: Path) -> list[PdfRecord]:
    return [
        PdfRecord(
            file_name="alpha.pdf",
            full_path=str(tmp_path / "alpha.pdf"),
            parent_folder=str(tmp_path),
            file_size_bytes=1024,
            created_date=datetime(2026, 1, 1, 12, 0, 0),
            modified_date=datetime(2026, 1, 2, 12, 0, 0),
            page_count=1,
            title="Alpha",
            encrypted=False,
            text_extractable=True,
            text_preview="Alpha preview",
        ),
        PdfRecord(
            file_name="beta.pdf",
            full_path=str(tmp_path / "beta.pdf"),
            parent_folder=str(tmp_path / "other"),
            file_size_bytes=4096,
            created_date=datetime(2026, 1, 3, 12, 0, 0),
            modified_date=datetime(2026, 1, 4, 12, 0, 0),
            page_count=5,
            title="Beta",
            encrypted=True,
            text_extractable=False,
            text_preview=None,
            error="Encrypted",
        ),
    ]


@pytest.fixture
def temporary_export_path(tmp_path: Path) -> Path:
    return tmp_path / "export.xlsx"


@pytest.fixture
def temporary_config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"
