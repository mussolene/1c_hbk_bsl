"""
Import platform API from vsc-language-1c-bsl bslGlobals.json.

Downloads (or reads) bslGlobals.json from 1c-syntax/vsc-language-1c-bsl
and converts it to per-type JSON files in data/platform_api/.

The LSP server loads these files at startup — no runtime network dependency.

Usage:
    # Download and import:
    python scripts/import_bsl_globals.py

    # Use local file:
    python scripts/import_bsl_globals.py /path/to/bslGlobals.json

Source:
    https://raw.githubusercontent.com/1c-syntax/vsc-language-1c-bsl/master/lib/bslGlobals.json
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BSL_GLOBALS_URL = (
    "https://raw.githubusercontent.com/1c-syntax/vsc-language-1c-bsl"
    "/master/lib/bslGlobals.json"
)
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "platform_api"
GLOBAL_FUNCTIONS_FILE = Path(__file__).parent.parent / "data" / "platform_api_globals.json"


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _convert_signature(sig_obj: dict | str | None, method_name: str) -> str:
    """Convert bslGlobals signature format → simple string like 'Method(Param1, Param2?)'."""
    if not sig_obj:
        return f"{method_name}()"
    if isinstance(sig_obj, str):
        return sig_obj

    default = sig_obj.get("default") or sig_obj.get("0") or (
        next(iter(sig_obj.values())) if sig_obj else None
    )
    if not default:
        return f"{method_name}()"

    # "СтрокаПараметров" is the full signature string "(Param1: Тип, Param2?: Тип): ReturnType"
    param_str = default.get("СтрокаПараметров", "")
    if param_str:
        # Extract just param part (drop return type after last ":")
        return f"{method_name}{param_str}"

    params = default.get("Параметры", {})
    if params:
        parts = list(params.keys())
        return f"{method_name}({', '.join(parts)})"
    return f"{method_name}()"


def _extract_return_type(returns_str: str | None) -> str:
    """Extract short return type from verbose description."""
    if not returns_str:
        return ""
    # "Тип: ТаблицаЗначений. Описание..."
    if returns_str.startswith("Тип:"):
        part = returns_str[4:].strip()
        # Take up to first period or semicolon
        for sep in (".", ";", "\n"):
            idx = part.find(sep)
            if idx > 0:
                return part[:idx].strip()
        return part[:100].strip()
    # "Type: ValueTable. Description"
    if "Type:" in returns_str:
        part = returns_str.split("Type:", 1)[1].strip()
        for sep in (".", ";", "\n"):
            idx = part.find(sep)
            if idx > 0:
                return part[:idx].strip()
    return ""


def _convert_method(name: str, m: dict) -> dict:
    sig = _convert_signature(m.get("signature"), name)
    return {
        "name": name,
        "name_en": m.get("name_en", ""),
        "signature": sig,
        "description": (m.get("description") or "")[:500],
        "returns": _extract_return_type(m.get("returns")),
    }


def _convert_property(name: str, p: dict) -> dict:
    return {
        "name": name,
        "name_en": p.get("name_en", ""),
        "description": (p.get("description") or "")[:300],
        "read_only": bool(p.get("read_only", False)),
    }


def _convert_class(name: str, cls: dict) -> dict:
    methods = [
        _convert_method(mname, m)
        for mname, m in (cls.get("methods") or {}).items()
    ]
    properties = [
        _convert_property(pname, p)
        for pname, p in (cls.get("properties") or {}).items()
    ]
    return {
        "name": name,
        "name_en": cls.get("name_en", ""),
        "kind": "class",
        "description": (cls.get("description") or "")[:500],
        "methods": methods,
        "properties": properties,
    }


def _convert_global_function(name: str, fn: dict) -> dict:
    sig = _convert_signature(fn.get("signature"), name)
    return {
        "name": name,
        "name_en": fn.get("name_en", ""),
        "kind": "function",
        "signature": sig,
        "description": (fn.get("description") or "")[:500],
        "returns": _extract_return_type(fn.get("returns")),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_bsl_globals(path: str | None) -> dict:
    if path:
        print(f"Reading {path}")
        return json.loads(Path(path).read_text(encoding="utf-8"))

    print(f"Downloading from {BSL_GLOBALS_URL}")
    with urllib.request.urlopen(BSL_GLOBALS_URL, timeout=30) as resp:  # noqa: S310
        data = resp.read()
    print(f"Downloaded {len(data):,} bytes")
    return json.loads(data)


def main() -> None:
    source_path = sys.argv[1] if len(sys.argv) > 1 else None
    raw = load_bsl_globals(source_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Convert classes
    classes = raw.get("classes", {})
    print(f"\nConverting {len(classes)} classes...")
    for name, cls in classes.items():
        converted = _convert_class(name, cls)
        out = OUTPUT_DIR / f"{name.lower()}.json"
        out.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Written to {OUTPUT_DIR}/")

    # 2. Convert global functions → single file
    gfuncs = raw.get("globalfunctions", {})
    print(f"\nConverting {len(gfuncs)} global functions...")
    converted_globals = [_convert_global_function(name, fn) for name, fn in gfuncs.items()]

    # Also add global variables
    gvars = raw.get("globalvariables", {})
    print(f"Converting {len(gvars)} global variables...")
    for name, var in gvars.items():
        converted_globals.append({
            "name": name,
            "name_en": var.get("name_en", ""),
            "kind": "variable",
            "signature": name,
            "description": (var.get("description") or "")[:300],
            "returns": "",
        })

    globals_file = OUTPUT_DIR / "_globals.json"
    globals_file.write_text(
        json.dumps(converted_globals, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Written to {globals_file.name}")

    # 3. Summary
    total_methods = sum(
        len(json.loads((OUTPUT_DIR / f"{n.lower()}.json").read_text()).get("methods", []))
        for n in classes
    )
    print("\nDone:")
    print(f"  {len(classes)} type files in data/platform_api/")
    print(f"  {total_methods} methods total")
    print(f"  {len(converted_globals)} global functions/variables in _globals.json")
    print("\nCommit data/platform_api/ to include in LSP server.")


if __name__ == "__main__":
    main()
