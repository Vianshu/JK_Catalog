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

    # --- Load stylesheet with absolute path (works in EXE too) ---
    style_path = get_asset_path("style.qss")
    load_stylesheet(app, style_path)

    window = MainWindow()
    window.showMaximized()
    
    sys.exit(app.exec())

# Suppress Font Warnings
from PyQt6.QtCore import qInstallMessageHandler
def qt_message_handler(mode, context, message):
    if "OpenType support missing" in message:
        return
    # Pass others to default or print
    print(message)

qInstallMessageHandler(qt_message_handler)

if __name__ == "__main__":
    main()