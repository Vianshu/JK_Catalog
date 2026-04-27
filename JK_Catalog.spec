# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
# ============================================================
# JK_Catalog PyInstaller Spec File
# ============================================================
# Builds a single-file Windows EXE.
#
# BUILD COMMAND:
#   pyinstaller JK_Catalog.spec
#
# IMPORTANT NOTES:
# - console=False: No terminal window. Crashes are logged to
#   data/error.log via main.py's global exception handler.
# - Data files are bundled INTO the EXE (extracted to _MEIPASS
#   at runtime). They are READ-ONLY.
# - Writable data (company DBs, logs) live next to the EXE,
#   not inside _MEIPASS. See path_utils.py for details.
# ============================================================


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # --- Bundled Data Files ---
    # These are extracted to sys._MEIPASS at runtime (read-only).
    # Access via: get_asset_path("style.qss") or get_data_file_path("super_master.db")
    datas=[
        ('src/assets/style.qss', 'src/assets'),       # UI stylesheet
        ('config/cleaning_rules.json', 'config'),      # Product name cleaning rules
        ('config/catalog_config.json', 'config'),      # Per-company catalog header config
    ] + collect_data_files('nepali_datetime'),

    hiddenimports=[],
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

splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='JK_Catalog',
    icon='JK_Icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                              # Compress with UPX for smaller EXE
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                          # No console window (GUI app)
    disable_windowed_traceback=False,       # Keep traceback in windowed mode
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

