# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec: single-file CLI (LSP, MCP, --check, --index, …).

Build from repo root:
  python -m PyInstaller --clean --noconfirm --workpath build/pyinstaller --distpath dist packaging/onec-hbk-bsl.spec

Dependency closure comes from Analysis() tracing imports from __main__.py — not from whatever
extra packages happen to be installed in the build venv. Only non-import assets we add below.

SPECPATH: directory containing this spec (set by PyInstaller).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).resolve().parent
SRC_MAIN = ROOT / "src" / "onec_hbk_bsl" / "__main__.py"

# Project data. certifi/jsonschema/etc. come from PyInstaller hooks via the import graph.
datas: list = [(str(ROOT / "data"), "data")]
# fastmcp reads __version__ via importlib.metadata.version("fastmcp") at import time — needs dist-info in the bundle.
datas += copy_metadata("fastmcp")

binaries: list = []

# Lazy / optional submodules some stacks load at runtime (keep minimal; expand only if WARN logs show misses)
hiddenimports: list = [
    # stdlib re-export paths uvicorn uses
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

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
