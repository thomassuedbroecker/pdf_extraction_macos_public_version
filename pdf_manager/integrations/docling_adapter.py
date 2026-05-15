"""Optional Docling document extraction adapter."""

from __future__ import annotations

import importlib.util


def is_docling_available() -> bool:
    """Return whether the optional Docling package can be imported."""
    try:
        return importlib.util.find_spec("docling.document_converter") is not None
    except (ModuleNotFoundError, ValueError):
        return False


class DoclingAdapter:
    """Adapter around Docling structured document processing.

    Docling is intentionally imported lazily so the normal application can run
    without installing the optional dependency.
    """

    def extract_text(self, path: str) -> str:
        """Extract PDF text through Docling and return Markdown-style text."""
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RuntimeError(
                "Docling is not installed. Install Docling to use the slower structured extraction option."
            ) from exc

        result = DocumentConverter().convert(path)
        document = getattr(result, "document", None)
        if document is None:
            return ""
        if hasattr(document, "export_to_markdown"):
            return str(document.export_to_markdown()).strip()
        if hasattr(document, "export_to_text"):
            return str(document.export_to_text()).strip()
        return str(document).strip()

    def extract_document_structure(self, path: str) -> dict:
        """Extract structured PDF content when Docling is installed."""
        text = self.extract_text(path)
        return {"text": text}
