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

import spellchecker
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
SRC_MAIN = ROOT / "src" / "onec_hbk_bsl" / "__main__.py"

# Project data. certifi/jsonschema/etc. come from PyInstaller hooks via the import graph.
datas: list = [(str(ROOT / "data"), "data")]
# MCP SDK may use importlib.metadata at runtime; keep its dist-info in the bundle.
datas += copy_metadata("mcp")
# Keep project metadata available in the bundle; runtime version lookup itself
# falls back to generated _version.py when frozen.
datas += copy_metadata("onec-hbk-bsl-core")
# Typo parity uses importlib.resources against this package at runtime.
datas += collect_data_files("onec_hbk_bsl.analysis.bsl_typo")
# BSL256 uses SpellChecker(language="ru"); keep only that dictionary in the bundle.
SPELLCHECKER_ROOT = Path(spellchecker.__file__).resolve().parent
datas += [
    (
        str(SPELLCHECKER_ROOT / "resources" / "ru.json.gz"),
        "spellchecker/resources",
    )
]

binaries: list = []

# Lazy / optional submodules some stacks load at runtime (keep minimal; expand only if WARN logs show misses)
hiddenimports: list = [
    # stdlib re-export paths uvicorn uses
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "spellchecker",
]
hiddenimports += collect_submodules("onec_hbk_bsl.analysis.diagnostic")

excludes = [
    "setuptools_scm",
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
    "cryptography",
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
