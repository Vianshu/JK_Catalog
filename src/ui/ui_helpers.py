"""
ui_helpers.py -- Shared, reusable UI utility functions.

Import individual helpers instead of copy-pasting the same boilerplate
across multiple widget classes.
"""

import os
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget


def pick_export_folder(
    parent,
    settings,
    settings_key: str = "export_folder",
    current_folder: str = "",
    title: str = "Select Export Folder",
) -> str:
    """Open a native folder-picker dialog and persist the chosen path.

    Args:
        parent:        The calling QWidget (used as dialog parent).
        settings:      A QSettings instance where the path is saved.
        settings_key:  The key under which the folder path is stored.
        current_folder: Pre-selected starting directory (may be empty).
        title:         Dialog window title.

    Returns:
        The selected folder path (str), or the unchanged current_folder if
        the user cancelled.
    """
    start_dir = current_folder if current_folder and os.path.exists(current_folder) else ""
    folder = QFileDialog.getExistingDirectory(parent, title, start_dir)
    if folder:
        settings.setValue(settings_key, folder)
        QMessageBox.information(
            parent,
            "Location Set",
            f"Export folder saved to:\n{folder}",
        )
        return folder
    return current_folder
