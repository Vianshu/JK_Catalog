import sys
import os
import traceback
import logging
from datetime import datetime
from PyQt6.QtWidgets import QApplication
from src.utils.path_utils import get_asset_path, get_app_dir

# --- Global Crash Logger ---
def setup_crash_logger():
    """Set up a global exception handler that logs crashes to error.log.
    This is critical for EXE mode where console=False means no stdout."""
    # Place error.log next to the EXE/main.py (not in bundled data/ folder)
    log_path = os.path.join(get_app_dir(), "error.log")
    
    # Configure file logger with fallback
    try:
        logging.basicConfig(
            filename=log_path,
            level=logging.ERROR,
            format='%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    except PermissionError:
        # Fallback: use temp directory if app dir is not writable
        import tempfile
        log_path = os.path.join(tempfile.gettempdir(), "jk_catalog_error.log")
        logging.basicConfig(
            filename=log_path,
            level=logging.ERROR,
            format='%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def global_exception_handler(exc_type, exc_value, exc_tb):
        """Catches all unhandled exceptions and writes them to error.log."""
        # Don't intercept KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        
        error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error(f"Unhandled Exception:\n{error_msg}")
        
        # Also print to stderr if available (development mode)
        print(f"[CRASH] {exc_type.__name__}: {exc_value}", file=sys.stderr)
        print(f"[CRASH] Full traceback saved to: {log_path}", file=sys.stderr)
    
    sys.excepthook = global_exception_handler
    print(f"[LOG] Crash logger active → {log_path}")

def load_stylesheet(app, file_name):
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            app.setStyleSheet(f.read())
    else:
        print(f"Warning: {file_name} file not found!")

def main():
    # Initialize crash logger FIRST, before anything else
    setup_crash_logger()
    app = QApplication(sys.argv)

    # --- Animated Splash Screen ---
    from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont
    from PyQt6.QtWidgets import QSplashScreen
    from PyQt6.QtCore import Qt
    splash_pix = QPixmap(500, 300)
    splash_pix.fill(QColor("#1e272e"))
    painter = QPainter(splash_pix)
    painter.setPen(QColor("#ecf0f1"))
    painter.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
    painter.drawText(splash_pix.rect(), Qt.AlignmentFlag.AlignCenter, "JK Catalog Loading...")
    
    painter.setPen(QColor("#3498db"))
    painter.setFont(QFont("Segoe UI", 12))
    painter.drawText(0, 0, 500, 270, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "Please wait while the application starts")
    painter.end()

    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # Heavy import AFTER splash is visible — MainWindow pulls in 20+ modules
    from src.ui.main_window import MainWindow

    # --- Enforce Fusion Style (Cross-platform consistency) ---
    from PyQt6.QtWidgets import QStyleFactory
    from PyQt6.QtGui import QPalette, QColor
    from PyQt6.QtCore import Qt

    app.setStyle(QStyleFactory.create("Fusion"))

    # --- Force Light Palette to ignore System Dark Mode ---
    light_palette = QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor(245, 245, 245))
    light_palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    light_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
    light_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    light_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    light_palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    light_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    light_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    light_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(light_palette)

    # --- Load stylesheet with absolute path (works in EXE too) ---
    style_path = get_asset_path("style.qss")
    load_stylesheet(app, style_path)

    window = MainWindow()
    window.maximize_window()
    
    # Close splash screen when window is ready
    splash.finish(window)
    
    sys.exit(app.exec())

# Suppress Font Warnings
from PyQt6.QtCore import qInstallMessageHandler
def qt_message_handler(mode, context, message):
    if "OpenType support missing" in message or "Point size <= 0" in message:
        return
    # Pass others to default or print
    print(message)

qInstallMessageHandler(qt_message_handler)

if __name__ == "__main__":
    main()