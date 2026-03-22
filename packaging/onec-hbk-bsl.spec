# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec: single-file CLI (LSP, MCP, --check, --index, …).

Build from repo root:
  python -m PyInstaller --clean --noconfirm --workpath build/pyinstaller --distpath dist packaging/onec-hbk-bsl.spec

SPECPATH: directory containing this spec (set by PyInstaller).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
SRC_MAIN = ROOT / "src" / "onec_hbk_bsl" / "__main__.py"

datas: list = [(str(ROOT / "data"), "data")]
binaries: list = []
hiddenimports: list = []

for pkg in (
    "tree_sitter",
    "tree_sitter_bsl",
    "fastmcp",
    "mcp",
    "uvicorn",
    "pygls",
    "rich",
    "watchfiles",
    "certifi",
    "jsonschema_specifications",
):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# Trim obvious dev / GUI / scientific stacks from the dependency graph (smaller bundle).
excludes = [
    "pytest",
    "_pytest",
    "unittest",
    "tkinter",
    "pydoc",
    "doctest",
    "matplotlib",
    "numpy",
    "pandas",
    "IPython",
]

block_cipher = None

a = Analysis(
    [str(SRC_MAIN)],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    a.datas,
    [],
    name="onec-hbk-bsl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=sys.platform != "win32",
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
