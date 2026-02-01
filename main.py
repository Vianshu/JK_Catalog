import sys
import os
from PyQt6.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.utils.path_utils import get_asset_path

def load_stylesheet(app, file_name):
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            app.setStyleSheet(f.read())
    else:
        print(f"Warning: {file_name} file not found!")

def main():
    app = QApplication(sys.argv)

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
    window.showMaximized()
    
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