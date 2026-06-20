"""Development helpers for compatibility inventory.

This module is intentionally outside ``src``: it supports local audits and
tests of the diagnostic registry, but it is not part of the runtime product.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def runtime_rule_codes_from_diagnostics_source(source: str) -> set[str]:
    """Collect BSL rule codes registered via ``_rule_tasks.append`` in source text."""
    raw_keys = set(
        re.findall(r'(?:_rule_tasks|tasks)\.append\(\s*\(\s*["\']([^"\']+)["\']', source)
    )
    out: set[str] = set()
    for key in raw_keys:
        if re.fullmatch(r"BSL\d{3}", key):
            out.add(key)
            continue
        range_match = re.fullmatch(r"BSL(\d{3})-(?:BSL)?(\d{3})", key)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            for num in range(start, end + 1):
                out.add(f"BSL{num:03d}")
            continue
        grouped_codes = re.findall(r"BSL\d{3}", key)
        if len(grouped_codes) >= 2:
            out.update(grouped_codes)
            continue
        parts = key.split("_")
        if parts and re.fullmatch(r"BSL\d{3}", parts[0]):
            head = parts[0]
            tail = parts[1:]
            if tail and all(re.fullmatch(r"\d{3}", part) for part in tail):
                out.add(head)
                out.update(f"BSL{part}" for part in tail)
    return out


def runtime_rule_codes_from_paths(paths: list[str | Path]) -> set[str]:
    """Collect runtime rule codes from one or more orchestration source files."""
    out: set[str] = set()
    for path in paths:
        out.update(
            runtime_rule_codes_from_diagnostics_source(Path(path).read_text(encoding="utf-8"))
        )
    return out


@dataclass(frozen=True, slots=True)
class CompatibilityRow:
    bsl_code: str | None
    current_name: str | None
    compatible_name: str | None
    exists_in_reference: bool
    has_runtime_branch: bool
    default_enabled: bool
    implemented_flag: bool | None
    category: str


def build_compatibility_rows(
    *,
    rule_metadata: dict[str, dict[str, Any]],
    reference_name_to_code: dict[str, str],
    runtime_rule_codes: set[str],
    default_disabled: set[str] | frozenset[str],
    reference_names: set[str] | None = None,
) -> list[CompatibilityRow]:
    """Build machine-readable compatibility rows for development audits."""
    canonical_names = set(reference_name_to_code)
    if reference_names:
        canonical_names |= set(reference_names)

    rows: list[CompatibilityRow] = []
    seen_current_names = {
        str(meta.get("name")) for meta in rule_metadata.values() if meta.get("name")
    }

    for code in sorted(rule_metadata):
        meta = rule_metadata[code]
        current_name = str(meta.get("name", "")) or None
        canonical_code = reference_name_to_code.get(current_name or "")
        exists_in_reference = bool(current_name and current_name in canonical_names)
        has_runtime_branch = code in runtime_rule_codes
        default_enabled = code not in default_disabled
        implemented_flag = meta.get("implemented")

        if exists_in_reference and canonical_code == code:
            category = "compatible"
        elif exists_in_reference:
            category = "alias/duplicate"
        else:
            category = "local-only"

        if not has_runtime_branch and exists_in_reference:
            category = "declared-not-run"
        elif has_runtime_branch and implemented_flag is False:
            category = "run-but-marked-false"

        rows.append(
            CompatibilityRow(
                bsl_code=code,
                current_name=current_name,
                compatible_name=current_name if exists_in_reference else None,
                exists_in_reference=exists_in_reference,
                has_runtime_branch=has_runtime_branch,
                default_enabled=default_enabled,
                implemented_flag=implemented_flag if isinstance(implemented_flag, bool) else None,
                category=category,
            )
        )

    missing_names = sorted(canonical_names - seen_current_names)
    for name in missing_names:
        rows.append(
            CompatibilityRow(
                bsl_code=None,
                current_name=None,
                compatible_name=name,
                exists_in_reference=True,
                has_runtime_branch=False,
                default_enabled=False,
                implemented_flag=None,
                category="missing-vs-reference",
            )
        )

    return rows


def compatibility_rows_as_jsonable(rows: list[CompatibilityRow]) -> list[dict[str, Any]]:
    """Convert dataclass rows to plain dicts for JSON output."""
    return [asdict(row) for row in rows]


def discover_reference_diagnostic_names(root: str | Path) -> set[str]:
    """Extract diagnostic names from a local Java diagnostic source checkout."""
    diag_dir = Path(root) / "src/main/java/com/github/_1c_syntax/bsl/languageserver/diagnostics"
    names: set[str] = set()
    if not diag_dir.is_dir():
        return names
    for file in diag_dir.glob("*Diagnostic.java"):
        stem = file.stem
        if stem.startswith("Abstract") or stem == "BSLDiagnostic":
            continue
        names.add(stem.removesuffix("Diagnostic"))
    return names
