# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH)
ICON_CANDIDATES = [
    ROOT / "assets" / "app_icon.ico",
    ROOT / "assets" / "naver_cafe_archive_icon.ico",
]
ICON_PATH = next((path for path in ICON_CANDIDATES if path.exists()), None)

datas = collect_data_files(
    "playwright",
    excludes=[
        "**/.local-browsers/**",
        "**/ms-playwright/**",
    ],
)
if ICON_PATH is not None:
    datas.append((str(ICON_PATH), "assets"))

hiddenimports = collect_submodules("playwright") + [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "playwright.sync_api",
]

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NaverCafeArchiveManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH is not None else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NaverCafeArchiveManager",
)
