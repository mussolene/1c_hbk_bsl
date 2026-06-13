#!/usr/bin/env python3
"""Build a static BSLLS diagnostics coverage matrix.

The script intentionally reads sources instead of executing diagnostics against
large BSL corpora. It compares upstream BSLLS Java diagnostics with the local
Python registry and implementation references, then writes compact artifacts for
planning parity work.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BSLLS_ROOT = Path(
    os.environ.get("BSLLS_SOURCE_ROOT", str(REPO_ROOT / ".nosync" / "bsl-language-server"))
)
BSLLS_DIAG_DIR = BSLLS_ROOT / "src/main/java/com/github/_1c_syntax/bsl/languageserver/diagnostics"
BSLLS_RES_DIR = (
    BSLLS_ROOT / "src/main/resources/com/github/_1c_syntax/bsl/languageserver/diagnostics"
)
LOCAL_ANALYSIS = REPO_ROOT / "src/onec_hbk_bsl/analysis"
LOCAL_DIAGNOSTICS = LOCAL_ANALYSIS / "diagnostics.py"
LOCAL_DIAG_PACKAGE = LOCAL_ANALYSIS / "diagnostic"
JSON_OUT = REPO_ROOT / ".agent/reports/bslls-diagnostics-matrix.json"
MD_OUT = REPO_ROOT / "docs/bslls-diagnostics-matrix.md"


@dataclass
class SourceRef:
    path: str
    line: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line}


@dataclass
class BsllsDiagnostic:
    name: str
    class_name: str
    source: SourceRef
    extends: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    ru_name: str = ""
    checks: list[SourceRef] = field(default_factory=list)


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def line_of(text: str, pattern: str) -> int:
    for idx, line in enumerate(text.splitlines(), 1):
        if pattern in line:
            return idx
    return 1


def find_matching_paren(text: str, start: int) -> int:
    depth = 0
    for pos in range(start, len(text)):
        char = text[pos]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos
    return -1


def parse_annotation_values(block: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in (
        "type",
        "severity",
        "scope",
        "minutesToFix",
        "activatedByDefault",
        "compatibilityMode",
        "canLocateOnProject",
        "extraMinForComplexity",
        "lspSeverity",
    ):
        match = re.search(rf"\b{key}\s*=\s*([^,\n)]+)", block)
        if match:
            value = match.group(1).strip().strip('"')
            values[key] = value.split(".")[-1]

    for key in ("tags", "modules"):
        match = re.search(rf"\b{key}\s*=\s*\{{(?P<body>.*?)\}}", block, re.S)
        if match:
            values[key] = [
                item.strip().split(".")[-1]
                for item in match.group("body").replace("\n", " ").split(",")
                if item.strip()
            ]
    return values


def read_properties(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    props: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def parse_bslls_diagnostics() -> list[BsllsDiagnostic]:
    if not BSLLS_DIAG_DIR.exists():
        raise SystemExit(
            f"BSLLS source tree is missing: {BSLLS_DIAG_DIR}. "
            "Clone upstream bsl-language-server source into the configured source directory first."
        )

    diagnostics: list[BsllsDiagnostic] = []
    for java_path in sorted(BSLLS_DIAG_DIR.glob("*Diagnostic.java")):
        text = read_text(java_path)
        if "@DiagnosticMetadata" not in text:
            continue

        class_match = re.search(
            r"public\s+class\s+(?P<class>\w+Diagnostic)\s+extends\s+(?P<extends>\w+)",
            text,
        )
        if not class_match:
            continue

        class_name = class_match.group("class")
        name = class_name.removesuffix("Diagnostic")
        class_line = line_of(text, f"class {class_name}")

        meta_start = text.find("@DiagnosticMetadata")
        open_paren = text.find("(", meta_start)
        close_paren = find_matching_paren(text, open_paren)
        meta_block = text[open_paren + 1 : close_paren] if close_paren != -1 else ""

        params: list[dict[str, Any]] = []
        for param_match in re.finditer(
            r"@DiagnosticParameter\s*\((?P<body>.*?)\)\s*(?P<field>[^;]+;)", text, re.S
        ):
            body = param_match.group("body")
            field_decl = " ".join(param_match.group("field").split())
            field_match = re.search(r"\b(?P<name>[A-Za-z_]\w*)\s*(?:=[^;]+)?;$", field_decl)
            type_match = re.search(r"type\s*=\s*([A-Za-z0-9_.]+)\.class", body)
            default_match = re.search(r"defaultValue\s*=\s*(?P<value>[^,\n)]+)", body)
            params.append(
                {
                    "name": field_match.group("name") if field_match else field_decl,
                    "type": type_match.group(1).split(".")[-1] if type_match else "",
                    "default": default_match.group("value").strip() if default_match else "",
                    "source": SourceRef(
                        rel(java_path), text[: param_match.start()].count("\n") + 1
                    ).as_dict(),
                }
            )

        checks = []
        for check_match in re.finditer(r"\b(check|visit[A-Z]\w*)\s*\(", text):
            checks.append(SourceRef(rel(java_path), text[: check_match.start()].count("\n") + 1))
        for add_match in re.finditer(r"diagnosticStorage\.addDiagnostic", text):
            checks.append(SourceRef(rel(java_path), text[: add_match.start()].count("\n") + 1))

        props = read_properties(BSLLS_RES_DIR / f"{class_name}_ru.properties")
        diagnostics.append(
            BsllsDiagnostic(
                name=name,
                class_name=class_name,
                source=SourceRef(rel(java_path), class_line),
                extends=class_match.group("extends"),
                metadata=parse_annotation_values(meta_block),
                parameters=params,
                message=props.get("diagnosticMessage", ""),
                ru_name=props.get("diagnosticName", ""),
                checks=checks[:12],
            )
        )
    return diagnostics


def fallback_bslls_diagnostics(name_to_code: dict[str, str]) -> list[BsllsDiagnostic]:
    """Build a reduced matrix from the embedded BSLLS name map when upstream source is absent."""
    return [
        BsllsDiagnostic(
            name=name,
            class_name=f"{name}Diagnostic",
            source=SourceRef(f"upstream:diagnostics/{name}Diagnostic.java", 1),
        )
        for name in sorted(name_to_code)
    ]


def parse_local_registry() -> tuple[dict[str, dict[str, Any]], dict[str, str], frozenset[str]]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.runner import (  # noqa: PLC0415
        DIAGNOSTIC_RUNTIME_RULE_CODES,
    )
    from onec_hbk_bsl.analysis.diagnostics import (  # noqa: PLC0415
        _BSLLS_NAME_TO_CODE,
        RULE_METADATA,
    )

    return dict(RULE_METADATA), dict(_BSLLS_NAME_TO_CODE), frozenset(DIAGNOSTIC_RUNTIME_RULE_CODES)


def parse_local_registry_from_source() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    tree = ast.parse(read_text(LOCAL_DIAGNOSTICS), filename=str(LOCAL_DIAGNOSTICS))
    metadata: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    for node in tree.body:
        target_names: list[str] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = [node.target.id]
            value = node.value
        if value is None:
            continue
        if "RULE_METADATA" in target_names:
            metadata = ast.literal_eval(value)
        elif "_BSLLS_NAME_TO_CODE" in target_names:
            names = ast.literal_eval(value)
    return metadata, names


def find_local_refs(
    metadata: dict[str, dict[str, Any]],
    runtime_rule_codes: frozenset[str],
) -> dict[str, dict[str, Any]]:
    py_files = [LOCAL_DIAGNOSTICS, *sorted(LOCAL_DIAG_PACKAGE.rglob("*.py"))]
    grouped_methods: dict[str, list[dict[str, Any]]] = {}
    grouped_method_re = re.compile(r"\bdef\s+(?P<name>(?:_rule_)?bsl(?:\d{3}_)+\d{3}\w*)\b", re.I)
    for path in py_files:
        text = read_text(path)
        for idx, line in enumerate(text.splitlines(), 1):
            for match in grouped_method_re.finditer(line):
                name = match.group("name")
                numbers = [int(value) for value in re.findall(r"\d{3}", name)]
                if numbers == [161, 168]:
                    numbers = list(range(161, 169))
                for number in numbers:
                    grouped_methods.setdefault(f"BSL{number:03d}", []).append(
                        {"name": name, **SourceRef(rel(path), idx).as_dict()}
                    )

    refs: dict[str, dict[str, Any]] = {}
    for code, meta in metadata.items():
        refs[code] = {
            "name": meta.get("name", ""),
            "metadata": None,
            "rule_methods": grouped_methods.get(code, []),
            "registrations": [],
            "emits": [],
            "code_refs": [],
        }
        method_re = re.compile(rf"\bdef\s+(_rule_bsl{code[3:].lower()}\w*)\b", re.I)
        code_literal_re = re.compile(rf"['\"]{re.escape(code)}['\"]")
        emit_re = re.compile(rf"\bcode\s*=\s*['\"]{re.escape(code)}['\"]")
        for path in py_files:
            text = read_text(path)
            for idx, line in enumerate(text.splitlines(), 1):
                if (
                    refs[code]["metadata"] is None
                    and path == LOCAL_DIAGNOSTICS
                    and (f'"{code}"' in line or f"'{code}'" in line)
                ):
                    refs[code]["metadata"] = SourceRef(rel(path), idx).as_dict()
                for match in method_re.finditer(line):
                    refs[code]["rule_methods"].append(
                        {"name": match.group(1), **SourceRef(rel(path), idx).as_dict()}
                    )
                if emit_re.search(line):
                    refs[code]["emits"].append(SourceRef(rel(path), idx).as_dict())
                if code_literal_re.search(line):
                    ref = SourceRef(rel(path), idx).as_dict()
                    if (
                        "/passes/" in rel(path)
                        or "_rule_enabled" in line
                        or "rule_tasks.append" in line
                        or "lambda:" in line
                        or "enabled_set" in line
                        or "enabled:" in line
                    ):
                        refs[code]["registrations"].append(ref)
                    else:
                        refs[code]["code_refs"].append(ref)
        if code in runtime_rule_codes:
            runner_path = LOCAL_DIAG_PACKAGE / "diagnostic_runtime" / "runner.py"
            refs[code]["registrations"].append(
                SourceRef(
                    rel(runner_path),
                    line_of(read_text(runner_path), "DIAGNOSTIC_RUNTIME_RULE_CODES"),
                ).as_dict()
            )
        # De-duplicate noisy references while preserving first useful lines.
        for key in ("rule_methods", "registrations", "emits", "code_refs"):
            seen = set()
            unique = []
            for item in refs[code][key]:
                marker = (item.get("path"), item.get("line"), item.get("name", ""))
                if marker not in seen:
                    seen.add(marker)
                    unique.append(item)
            refs[code][key] = unique[:20]
    return refs


def status_for(code: str | None, refs: dict[str, Any] | None, meta: dict[str, Any] | None) -> str:
    if not code or not meta:
        return "missing"
    if refs and refs["registrations"]:
        return "implemented"
    if refs and (refs["rule_methods"] or refs["emits"]):
        return "implemented_unregistered"
    return "metadata_only"


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    source_note = (
        "Источник BSLLS: upstream `bsl-language-server` develop, статическое чтение Java/properties."
        if payload.get("source_mode") == "upstream"
        else "Источник BSLLS: встроенная карта имён/кодов; внешний upstream source недоступен."
    )
    lines = [
        "# BSLLS diagnostics static matrix",
        "",
        source_note,
        "Локальный источник: `src/onec_hbk_bsl/analysis/diagnostics.py` и `src/onec_hbk_bsl/analysis/diagnostic/**`.",
        "",
        "## Summary",
        "",
        f"- BSLLS diagnostics: {summary['bslls_total']}",
        f"- Local rules: {summary['local_total']}",
        f"- Implemented by static refs: {summary['by_status'].get('implemented', 0)}",
        f"- Implemented but not registered clearly: {summary['by_status'].get('implemented_unregistered', 0)}",
        f"- Metadata only: {summary['by_status'].get('metadata_only', 0)}",
        f"- Missing in local map: {summary['by_status'].get('missing', 0)}",
        f"- Local-only rules: {summary['local_only_total']}",
        "",
        "## Priority gaps",
        "",
    ]
    for item in payload["priority_gaps"]:
        lines.append(
            f"- `{item['name']}`: status `{item['status']}`, BSLLS `{item['bslls_source']['path']}:{item['bslls_source']['line']}`"
        )
    if not payload["priority_gaps"]:
        lines.append("- No missing or metadata-only BSLLS diagnostics found by name.")

    lines.extend(
        [
            "",
            "## Matrix",
            "",
            "| BSLLS name | Local code | Status | BSLLS source | Type | Severity | Params | Local source |",
            "|---|---:|---|---|---|---|---|---|",
        ]
    )
    for item in payload["diagnostics"]:
        bslls_ref = f"{item['bslls_source']['path']}:{item['bslls_source']['line']}"
        local_ref = ""
        if item.get("local_metadata_source"):
            local_ref = (
                f"{item['local_metadata_source']['path']}:{item['local_metadata_source']['line']}"
            )
        if item.get("local_implementation_sources"):
            first_impl = item["local_implementation_sources"][0]
            local_ref = f"{first_impl['path']}:{first_impl['line']}"
        params = ", ".join(param["name"] for param in item["parameters"])
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{md_escape(item['name'])}`",
                    f"`{md_escape(item.get('local_code') or '')}`",
                    f"`{md_escape(item['status'])}`",
                    md_escape(bslls_ref),
                    md_escape(item["metadata"].get("type", "")),
                    md_escape(item["metadata"].get("severity", "")),
                    md_escape(params),
                    md_escape(local_ref),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Local-only rules", ""])
    for item in payload["local_only"]:
        lines.append(
            f"- `{item['code']}` `{item['name']}` at `{item['source']['path']}:{item['source']['line']}`"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    metadata, name_to_code, runtime_rule_codes = parse_local_registry()
    source_mode = "upstream"
    try:
        bslls = parse_bslls_diagnostics()
    except SystemExit as exc:
        source_mode = "embedded"
        print(str(exc), file=sys.stderr)
        print("Falling back to embedded BSLLS diagnostic name map.", file=sys.stderr)
        bslls = fallback_bslls_diagnostics(name_to_code)
    refs = find_local_refs(metadata, runtime_rule_codes)

    diagnostics = []
    bslls_names = {item.name for item in bslls}
    for item in bslls:
        local_code = name_to_code.get(item.name)
        local_meta = metadata.get(local_code or "")
        local_refs = refs.get(local_code or "")
        local_impl_sources = []
        if local_refs:
            local_impl_sources.extend(local_refs["rule_methods"])
            local_impl_sources.extend(local_refs["emits"])
            local_impl_sources.extend(local_refs["registrations"])
        diagnostics.append(
            {
                "name": item.name,
                "class_name": item.class_name,
                "bslls_source": item.source.as_dict(),
                "bslls_extends": item.extends,
                "metadata": item.metadata,
                "parameters": item.parameters,
                "message_ru": item.message,
                "name_ru": item.ru_name,
                "check_sources": [ref.as_dict() for ref in item.checks],
                "local_code": local_code,
                "local_name": local_meta.get("name") if local_meta else None,
                "local_metadata_source": local_refs.get("metadata") if local_refs else None,
                "local_implementation_sources": local_impl_sources[:20],
                "status": status_for(local_code, local_refs, local_meta),
            }
        )

    local_only = []
    bslls_name_fold = {name.casefold() for name in bslls_names}
    mapped_bslls_codes = {
        code for name, code in name_to_code.items() if name.casefold() in bslls_name_fold
    }
    for code, meta in sorted(metadata.items()):
        name = meta.get("name", "")
        if code not in mapped_bslls_codes and name.casefold() not in bslls_name_fold:
            source = refs.get(code, {}).get("metadata") or {
                "path": rel(LOCAL_DIAGNOSTICS),
                "line": 1,
            }
            local_only.append({"code": code, "name": name, "source": source})

    by_status = Counter(item["status"] for item in diagnostics)
    priority_statuses = {"missing", "metadata_only", "implemented_unregistered"}
    priority_gaps = [item for item in diagnostics if item["status"] in priority_statuses][:40]
    payload = {
        "source_mode": source_mode,
        "summary": {
            "bslls_total": len(diagnostics),
            "local_total": len(metadata),
            "by_status": dict(sorted(by_status.items())),
            "local_only_total": len(local_only),
        },
        "diagnostics": diagnostics,
        "local_only": local_only,
        "priority_gaps": priority_gaps,
    }

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    wrote_md = False
    if source_mode == "upstream":
        MD_OUT.write_text(render_markdown(payload), encoding="utf-8")
        wrote_md = True
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {rel(JSON_OUT)}")
    if wrote_md:
        print(f"wrote {rel(MD_OUT)}")
    else:
        print(f"skipped {rel(MD_OUT)} (embedded source mode)")


if __name__ == "__main__":
    main()
