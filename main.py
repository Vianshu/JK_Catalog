import sys
import os
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow

def load_stylesheet(app, file_name):
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            app.setStyleSheet(f.read())
    else:
        print(f"Warning: {file_name} file not found!")

def main():
    app = QApplication(sys.argv)

    # --- यहाँ स्टाइलशीट लोड की जा रही है ---
    load_stylesheet(app, "style.qss")

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()