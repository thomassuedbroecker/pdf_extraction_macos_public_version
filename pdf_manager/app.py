"""Application entry point for the PDF Manager desktop app."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from pdf_manager.core.config import AppConfig, configure_logging
from pdf_manager.ui.main_window import MainWindow


def main() -> int:
    """Run the desktop application."""
    config = AppConfig.load()
    configure_logging()
    logging.getLogger(__name__).info("Starting PDF Manager")

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Manager")
    app.setOrganizationName("Local PDF Tools")

    window = MainWindow(config=config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
