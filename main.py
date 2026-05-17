import sys
import os
import traceback
import logging
from datetime import datetime
from PyQt6.QtWidgets import QApplication
from src.utils.path_utils import get_asset_path, get_app_dir

# --- Global Crash Logger ---
def setup_crash_logger():
    """Set up unified logging (file + console) and a global crash handler.
    This is critical for EXE mode where console=False means no stdout."""
    from src.utils.app_logger import setup_file_logging, get_logger

    # Place error.log next to the EXE/main.py (not in bundled data/ folder)
    log_path = os.path.join(get_app_dir(), "error.log")
    actual_path = setup_file_logging(log_path)

    crash_logger = get_logger("crash")

    def global_exception_handler(exc_type, exc_value, exc_tb):
        """Catches all unhandled exceptions and writes them to error.log."""
        # Don't intercept KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_logger.critical(f"Unhandled Exception:\n{error_msg}")

        # Also print to stderr if available (development mode)
        print(f"[CRASH] {exc_type.__name__}: {exc_value}", file=sys.stderr)
        print(f"[CRASH] Full traceback saved to: {actual_path}", file=sys.stderr)

    sys.excepthook = global_exception_handler
    print(f"[LOG] Logger active -> {actual_path}")

def load_stylesheet(app, file_name):
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            app.setStyleSheet(f.read())
    else:
        print(f"Warning: {file_name} file not found!")


def check_first_launch_setup(app):
    """Show setup dialog if config.json is missing or incomplete.
    
    Must run BEFORE MainWindow/DBManager are imported, because
    DBManager reads config.json at import time.
    
    Returns True if setup is complete (existing or just configured).
    Returns False if user cancelled (app should exit).
    """
    import json
    from src.utils.path_utils import get_app_dir, get_exe_dir

    user_config = os.path.join(get_app_dir(), "config.json")
    exe_config = os.path.join(get_exe_dir(), "config.json")

    # Check if a valid config already exists
    for path in [user_config, exe_config]:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    has_path = data.get("default_path", "") and os.path.isdir(data["default_path"])
                    # sql_server_name is optional — defaults to .\SQLEXPRESS
                    if has_path:
                        return True
            except Exception:
                pass

    # No valid config found — show setup dialog
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
        QPushButton, QFileDialog, QMessageBox, QFrame
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont

    dlg = QDialog()
    dlg.setWindowTitle("JK Catalog Multi — First Time Setup")
    dlg.setFixedSize(520, 340)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)
    layout.setContentsMargins(24, 24, 24, 24)

    # Title
    title = QLabel("Welcome to JK Catalog Multi")
    title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    subtitle = QLabel("Please configure the application before first use.")
    subtitle.setFont(QFont("Segoe UI", 10))
    subtitle.setStyleSheet("color: #666;")
    subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(subtitle)

    # Separator
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #ddd;")
    layout.addWidget(line)

    # Data Path
    layout.addWidget(QLabel("📁 Data Folder Path:"))
    path_row = QHBoxLayout()
    path_input = QLineEdit()
    path_input.setPlaceholderText("Select where company data will be stored...")
    path_input.setMinimumHeight(32)
    browse_btn = QPushButton("Browse...")
    browse_btn.setMinimumHeight(32)
    browse_btn.setFixedWidth(90)
    path_row.addWidget(path_input)
    path_row.addWidget(browse_btn)
    layout.addLayout(path_row)

    def browse_folder():
        folder = QFileDialog.getExistingDirectory(dlg, "Select Data Folder", "")
        if folder:
            path_input.setText(folder)

    browse_btn.clicked.connect(browse_folder)

    # SQL Server
    layout.addWidget(QLabel("🗄️ SQL Server Instance Name:"))
    sql_input = QLineEdit(r".\SQLEXPRESS")
    sql_input.setMinimumHeight(32)
    sql_input.setPlaceholderText(r"e.g. .\SQLEXPRESS or SERVERNAME\SQLEXPRESS")
    layout.addWidget(sql_input)

    hint = QLabel("Leave default if SQL Server Express is installed locally.")
    hint.setStyleSheet("color: #888; font-size: 10px;")
    layout.addWidget(hint)

    layout.addStretch()

    # Buttons
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    save_btn = QPushButton("✅ Save && Continue")
    save_btn.setMinimumHeight(36)
    save_btn.setMinimumWidth(160)
    save_btn.setStyleSheet(
        "background-color: #28a745; color: white; font-weight: bold; "
        "border-radius: 4px; padding: 6px 16px;"
    )
    cancel_btn = QPushButton("Cancel")
    cancel_btn.setMinimumHeight(36)
    cancel_btn.setMinimumWidth(90)
    btn_row.addWidget(save_btn)
    btn_row.addWidget(cancel_btn)
    layout.addLayout(btn_row)

    result = {"accepted": False}

    def save_config():
        data_path = path_input.text().strip()
        sql_name = sql_input.text().strip() or r".\SQLEXPRESS"

        if not data_path:
            QMessageBox.warning(dlg, "Missing Path", "Please select a data folder path.")
            return

        # Create the folder if it doesn't exist
        os.makedirs(data_path, exist_ok=True)

        if not os.path.isdir(data_path):
            QMessageBox.warning(dlg, "Invalid Path", f"Cannot create folder:\n{data_path}")
            return

        config_data = {
            "default_path": data_path,
            "sql_server_name": sql_name,
        }

        # Save to user config
        try:
            os.makedirs(os.path.dirname(user_config), exist_ok=True)
            with open(user_config, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            QMessageBox.critical(dlg, "Error", f"Cannot save user config:\n{e}")
            return

        # Also save global config next to EXE (for other RDP users)
        if exe_config != user_config:
            try:
                with open(exe_config, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2)
            except Exception:
                pass  # Non-critical — user config is enough

        result["accepted"] = True
        dlg.accept()

    save_btn.clicked.connect(save_config)
    cancel_btn.clicked.connect(dlg.reject)

    dlg.exec()
    return result["accepted"]

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
    painter.drawText(splash_pix.rect(), Qt.AlignmentFlag.AlignCenter, "JK Catalog Multi Loading...")
    
    painter.setPen(QColor("#3498db"))
    painter.setFont(QFont("Segoe UI", 12))
    painter.drawText(0, 0, 500, 270, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "Please wait while the application starts")
    painter.end()

    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # --- First Launch Setup (before any DB imports) ---
    if not check_first_launch_setup(app):
        # User cancelled setup — exit cleanly
        sys.exit(0)

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
    
    # Close PyInstaller splash if running from EXE
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    # Close PyQt splash screen when window is ready
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