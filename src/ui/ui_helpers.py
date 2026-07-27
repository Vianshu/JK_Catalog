"""
ui_helpers.py -- Shared, reusable UI utility functions.

Import individual helpers instead of copy-pasting the same boilerplate
across multiple widget classes.
"""

import os
from PyQt6.QtWidgets import QFileDialog, QMessageBox


def pick_export_folder(
    parent,
    settings,
    settings_key: str = "export_folder",
    current_folder: str = "",
    title: str = "Select Export Folder",
) -> str:
    """Open a compact folder-picker dialog and persist the chosen path.

    Uses Qt's own (non-native) folder dialog so the window size can be
    controlled.  The native Windows dialog always opens full-screen and
    cannot be resized programmatically.

    Args:
        parent:         The calling QWidget (used as dialog parent).
        settings:       A QSettings instance where the path is saved.
        settings_key:   The key under which the folder path is stored.
        current_folder: Pre-selected starting directory (may be empty).
        title:          Dialog window title.

    Returns:
        The selected folder path (str), or the unchanged current_folder if
        the user cancelled.
    """
    start_dir = current_folder if current_folder and os.path.exists(current_folder) else ""

    dlg = QFileDialog(parent, title, start_dir)
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.resize(560, 420)

    if dlg.exec():
        selected = dlg.selectedFiles()
        folder = selected[0] if selected else ""
    else:
        folder = ""

    if folder:
        settings.setValue(settings_key, folder)
        QMessageBox.information(
            parent,
            "Location Set",
            f"Export folder saved to:\n{folder}",
        )
        return folder
    return current_folder
