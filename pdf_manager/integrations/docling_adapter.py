"""Placeholder interface for future Docling document extraction."""

from __future__ import annotations


class DoclingAdapter:
    """Future adapter around Docling structured document processing."""

    def extract_document_structure(self, path: str) -> dict:
        """Extract structured PDF content when implemented."""
        raise NotImplementedError("Docling integration is planned for a future version.")
