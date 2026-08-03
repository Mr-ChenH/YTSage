import os
import sys


def _configure_qt_logging() -> None:
    """Suppress noisy Qt font database warnings while preserving other Qt logs."""
    font_db_rule = "qt.text.font.db=false"
    existing_rules = os.environ.get("QT_LOGGING_RULES")
    if existing_rules:
        if font_db_rule not in existing_rules.split(";"):
            os.environ["QT_LOGGING_RULES"] = f"{existing_rules};{font_db_rule}"
    else:
        os.environ["QT_LOGGING_RULES"] = font_db_rule


_configure_qt_logging()

from PySide6.QtWidgets import QApplication, QMessageBox

from .utils.ytsage_logger import logger
from .gui.ytsage_gui_main import YTSageApp  # Import the main application class from ytsage_gui_main


def show_error_dialog(message):
    error_dialog = QMessageBox()
    error_dialog.setIcon(QMessageBox.Icon.Critical)
    error_dialog.setText("Application Error")
    error_dialog.setInformativeText(message)
    error_dialog.setWindowTitle("Error")
    error_dialog.exec()


def main():
    try:
        logger.info("Starting YTSage application")
        app = QApplication(sys.argv)

        window = YTSageApp()  # Instantiate the main application class
        window.show()
        logger.info("Application window shown, entering main loop")
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"Critical application error: {e}", exc_info=True)
        show_error_dialog(f"Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
