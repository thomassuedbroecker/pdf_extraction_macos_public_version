"""Placeholder interface for future agent-based PDF inspection."""

from __future__ import annotations

from pdf_manager.models.pdf_record import PdfRecord


class AgentInterface:
    """Future agent workflow boundary for PDF inspection."""

    def inspect_pdf(self, record: PdfRecord) -> dict:
        """Inspect a PDF record with an agent workflow when implemented."""
        raise NotImplementedError("Agent-based inspection is planned for a future version.")
