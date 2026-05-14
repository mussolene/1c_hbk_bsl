"""BSLLS parity matrix and default-rule helpers.

This module centralizes the mapping between the local diagnostics registry and
the reference BSLLS rule names. It is the runtime source of truth for:

- the default BSLLS-compatible rule set
- machine-readable parity matrix generation for docs/tests
- categorisation of local-only and duplicate rules
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BSLLS_OS_ONLY_NAMES = frozenset(
    {
        "UnusedParameters",
    }
)
BSLLS_DEFAULT_DISABLED_NAMES = frozenset(
    {
        "BadWords",
        "CodeOutOfRegion",
        "CodeAfterAsyncCall",
        "DenyIncompleteValues",
        "FieldsFromJoinsWithoutIsNull",
        "FileSystemAccess",
        "FunctionNameStartsWithGet",
        "FunctionOutParameter",
        "InternetAccess",
        "MissingTempStorageDeletion",
        "TernaryOperatorUsage",
        "TooManyReturns",
        "UseSystemInformation",
        "UsingLikeInQuery",
        "ServerSideExportFormMethod",
    }
)


def runtime_rule_codes_from_diagnostics_source(source: str) -> set[str]:
    """Collect BSL rule codes registered via ``_rule_tasks.append`` in ``diagnostics.py``.

    Ruff may break ``append`` calls across lines or place the ``\"BSLnnn\"`` token on its
    own line inside a nested tuple; this must stay in sync with tests and
    the current BSLLS oracle/parity tooling.
    """
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
class ParityRow:
    bsl_code: str | None
    current_name: str | None
    bslls_name: str | None
    exists_in_bslls: bool
    has_runtime_branch: bool
    default_enabled: bool
    implemented_flag: bool | None
    category: str


def default_bslls_rule_codes(
    bslls_name_to_code: dict[str, str],
    *,
    default_disabled_codes: set[str] | frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Canonical BSLLS-compatible rule set aligned with BSLLS defaults."""
    return frozenset(
        code
        for name, code in bslls_name_to_code.items()
        if code not in default_disabled_codes
        and name not in BSLLS_OS_ONLY_NAMES
        and name not in BSLLS_DEFAULT_DISABLED_NAMES
    )


def merge_default_with_select(
    select: set[str] | None,
    bslls_name_to_code: dict[str, str],
    *,
    default_disabled_codes: set[str] | frozenset[str] = frozenset(),
) -> set[str]:
    """
    Combine explicit ``select`` with the canonical default rule set.

    Without an explicit selection, only the canonical BSLLS-compatible default
    rule set is active. Explicit selection runs the requested BSLLS rules,
    including rules that BSLLS disables by default, but never exposes local-only
    rules as selectable diagnostics.
    """
    default_select = set(
        default_bslls_rule_codes(
            bslls_name_to_code,
            default_disabled_codes=default_disabled_codes,
        )
    )
    if not select:
        return default_select
    return set(select) & set(bslls_name_to_code.values())


# Backward-compatible helper name for tests/tools that still describe the oracle
# relationship as "BSLLS". It is not a runtime profile or user mode.
def bslls_rule_codes(
    bslls_name_to_code: dict[str, str],
    *,
    default_disabled_codes: set[str] | frozenset[str] = frozenset(),
) -> frozenset[str]:
    return default_bslls_rule_codes(
        bslls_name_to_code,
        default_disabled_codes=default_disabled_codes,
    )


def build_parity_rows(
    *,
    rule_metadata: dict[str, dict[str, Any]],
    bslls_name_to_code: dict[str, str],
    runtime_rule_codes: set[str],
    default_disabled: set[str] | frozenset[str],
    bslls_names: set[str] | None = None,
) -> list[ParityRow]:
    """
    Build a machine-readable parity matrix.

    ``bslls_names`` may include names discovered from the Java BSLLS project. If
    omitted, the canonical mapping keys are used as the known BSLLS set.
    """
    canonical_names = set(bslls_name_to_code)
    if bslls_names:
        canonical_names |= set(bslls_names)

    rows: list[ParityRow] = []
    seen_current_names = {
        str(meta.get("name")) for meta in rule_metadata.values() if meta.get("name")
    }

    for code in sorted(rule_metadata):
        meta = rule_metadata[code]
        current_name = str(meta.get("name", "")) or None
        canonical_code = bslls_name_to_code.get(current_name or "")
        exists_in_bslls = bool(current_name and current_name in canonical_names)
        has_runtime_branch = code in runtime_rule_codes
        default_enabled = code not in default_disabled
        implemented_flag = meta.get("implemented")

        if exists_in_bslls and canonical_code == code:
            category = "parity"
        elif exists_in_bslls:
            category = "alias/duplicate"
        else:
            category = "local-only"

        if not has_runtime_branch and exists_in_bslls:
            category = "declared-not-run"
        elif has_runtime_branch and implemented_flag is False:
            category = "run-but-marked-false"

        rows.append(
            ParityRow(
                bsl_code=code,
                current_name=current_name,
                bslls_name=current_name if exists_in_bslls else None,
                exists_in_bslls=exists_in_bslls,
                has_runtime_branch=has_runtime_branch,
                default_enabled=default_enabled,
                implemented_flag=implemented_flag if isinstance(implemented_flag, bool) else None,
                category=category,
            )
        )

    missing_names = sorted(canonical_names - seen_current_names)
    for name in missing_names:
        rows.append(
            ParityRow(
                bsl_code=None,
                current_name=None,
                bslls_name=name,
                exists_in_bslls=True,
                has_runtime_branch=False,
                default_enabled=False,
                implemented_flag=None,
                category="missing-vs-bslls",
            )
        )

    return rows


def parity_rows_as_jsonable(rows: list[ParityRow]) -> list[dict[str, Any]]:
    """Convert dataclass rows to plain dicts for JSON output."""
    return [asdict(row) for row in rows]


def discover_bslls_names_from_repo(root: str | Path) -> set[str]:
    """Extract concrete BSLLS diagnostic names from a local Java checkout."""
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
