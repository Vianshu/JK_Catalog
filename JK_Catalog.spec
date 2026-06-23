# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
# ============================================================
# JK Catalog (Single-User) — PyInstaller Spec File
# ============================================================
# Builds a ONE-DIR Windows distribution.
# Wrap with JK_Catalog_Setup.iss to produce JK_Catalog_Setup.exe
#
# BUILD COMMAND:
#   pyinstaller JK_Catalog.spec --noconfirm
#
# IMPORTANT NOTES:
# - console=False: No terminal window. Crashes are logged to
#   %APPDATA%/JK_Catalog/error.log via main.py's global handler.
# - Bundled read-only assets live in _internal/ (sys._MEIPASS).
# - Writable data (config, logs) go to %APPDATA%/JK_Catalog/
#   via path_utils.get_app_dir(). Nothing is stored next to the exe.
# ============================================================


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # --- Bundled Data Files ---
    # Extracted to sys._MEIPASS (_internal/) at runtime — READ-ONLY.
    # Access via get_asset_path() / get_base_path().
    datas=[
        ('splash.png', '.'),                          # Splash image for QSplashScreen
        ('src/assets/style.qss', 'src/assets'),       # UI stylesheet
        ('config/cleaning_rules.json', 'config'),      # Product name cleaning rules
        ('config/catalog_config.json', 'config'),      # Per-company catalog config
    ] + collect_data_files('nepali_datetime'),

    hiddenimports=['pyodbc'],   # ODBC driver (auto-detect misses it)
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    exclude_binaries=True,          # Binaries go into COLLECT (one-dir)
    name='JK_Catalog',
    icon='JK_Icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # No console window (GUI app)
    disable_windowed_traceback=False,
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
    name='JK_Catalog'
)
