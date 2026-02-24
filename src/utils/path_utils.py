"""
Utility module for handling paths in both development and EXE (frozen) mode.
"""
import sys
import os


def get_base_path():
    """
    Get base path - works for both development and frozen (EXE) mode.
    
    When running as script: Returns the project root directory
    When running as EXE: Returns sys._MEIPASS (temp extraction folder)
    
    Use this for READ-ONLY bundled files like style.qss, super_master.db
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE - bundled files are in _MEIPASS
        return sys._MEIPASS
    else:
        # Running as script - go up from src/utils to project root
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_app_dir():
    """
    Get the directory where the EXE is located (or script's directory in dev mode).
    
    Use this for WRITABLE data that should persist (like godown_stock.db, logs, etc.)
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE - return the folder containing the EXE
        return os.path.dirname(sys.executable)
    else:
        # Running as script - project root
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_data_file_path(filename):
    """
    Get path to a core data file (super_master.db, calendar_data.db, etc.)
    These are bundled inside the EXE (READ-ONLY).
    
    Args:
        filename: Just the filename, e.g., "super_master.db"
    
    Returns:
        Full absolute path to the file
    """
    if filename == "super_master.db":
        import json
        app_path = get_app_dir()
        config_file = os.path.join(app_path, "config.json")
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    data_path = json.load(f).get("default_path", "")
                    if data_path and os.path.exists(data_path):
                        return os.path.join(data_path, filename)
        except Exception:
            pass

    base = get_base_path()
    return os.path.join(base, "data", filename)


def get_asset_path(filename):
    """
    Get path to an asset file (style.qss, etc.)
    
    Args:
        filename: Just the filename, e.g., "style.qss"
    
    Returns:
        Full absolute path to the file
    """
    base = get_base_path()
    return os.path.join(base, "src", "assets", filename)


def get_writable_data_path(subfolder=""):
    """
    Get path to a writable data folder (for godown_stock.db, temp files, etc.)
    This is in the EXE's directory, NOT the bundled _MEIPASS.
    
    Args:
        subfolder: Optional subfolder name, e.g., "Temp"
    
    Returns:
        Full absolute path to the writable folder (creates it if needed)
    """
    base = get_app_dir()
    path = os.path.join(base, "data", subfolder) if subfolder else os.path.join(base, "data")
    os.makedirs(path, exist_ok=True)
    return path
