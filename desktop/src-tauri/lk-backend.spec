# PyInstaller spec for the LABKickstart backend sidecar.
# --onefile mode: single self-contained executable that self-extracts
# at launch. Required because Tauri's externalBin mechanism ships only
# the launcher binary, not sibling _internal/ directory contents.
# Run via desktop/build.py — do not invoke directly.
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    # collect_all('labkickstart') misses the static dir when the package
    # is imported via PYTHONPATH=src rather than installed; bundle it
    # explicitly.
    ('../../src/labkickstart/static', 'labkickstart/static'),
]
binaries = []
hiddenimports = []
for pkg in ("bleak", "uvicorn", "labkickstart", "fastapi", "starlette"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['../../src/labkickstart/__main__.py'],
    pathex=['../../src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='lk-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
