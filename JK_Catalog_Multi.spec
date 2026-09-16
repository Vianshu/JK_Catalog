# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
# ============================================================
# JK Catalog Multi — PyInstaller Spec File
# ============================================================
# Builds a one-dir (folder) Windows application for the MULTI-USER version.
# Includes SQL Server (pyodbc), RBAC security, and multi-company
# support designed for RDP-based deployments.
#
# BUILD COMMAND:
#   pyinstaller JK_Catalog_Multi.spec
#
# IMPORTANT NOTES:
# - console=False: No terminal window. Crashes are logged to
#   error.log via main.py's global exception handler.
# - Data files are bundled INTO the EXE (extracted to _MEIPASS
#   at runtime). They are READ-ONLY.
# - Writable data (SQL Server DBs, logs, config) live in
#   %APPDATA%/JK_Catalog_Multi/ per user. See path_utils.py.
# ============================================================


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # --- Bundled Data Files ---
    # These are extracted to sys._MEIPASS at runtime (read-only).
    datas=[
        ('splash.png', '.'),                          # Splash image for PyQt
        ('JK_Icon.ico', '.'),                         # Window Icon
        ('src/assets/style.qss', 'src/assets'),       # UI stylesheet
        ('src/assets/fonts', 'src/assets/fonts'),     # Bundled fonts (Noto Sans Devanagari, etc.)
        ('src/ui/icons', 'src/ui/icons'),             # UI SVG Icons (Missing fix)
        ('config/cleaning_rules.json', 'config'),      # Product name cleaning rules
        ('config/catalog_config.json', 'config'),      # Per-company catalog header config
    ] + collect_data_files('nepali_datetime'),

    hiddenimports=['pyodbc', 'xlsxwriter'],   # SQL Server driver + Excel writer (auto-detect misses it)
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # --- Excluded Packages ---
    # These are large packages that PyInstaller might detect as dependencies
    # but are NOT used by this application. Excluding them reduces EXE size significantly.
    excludes=[
        'torch', 'scipy', 'tensorflow', 'matplotlib',
        'PySide6', 'PySide2', 'PyQt5', 'QtPy',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JK_Catalog_Multi',
    icon='JK_Icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                              # Compress with UPX for smaller EXE
    console=False,                          # No console window (GUI app)
    disable_windowed_traceback=False,       # Keep traceback in windowed mode
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JK_Catalog_Multi'
)
