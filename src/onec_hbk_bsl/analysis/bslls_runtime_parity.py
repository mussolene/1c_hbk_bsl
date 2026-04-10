"""Runtime parity helpers for comparing onec-hbk-bsl against Java BSLLS."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from onec_hbk_bsl.analysis.diagnostics import (
    _BSLLS_NAME_TO_CODE,
    RULE_METADATA,
    Diagnostic,
    DiagnosticEngine,
    lsp_compat_severity,
)
from onec_hbk_bsl.analysis.formatter import BslFormatter
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

BSL_SUFFIXES = frozenset({".bsl", ".os"})
_CODE_TO_BSLLS_NAME = {code: name for name, code in _BSLLS_NAME_TO_CODE.items()}


@dataclass(frozen=True, slots=True)
class NormalizedDiagnostic:
    file: str
    line: int
    character: int
    severity: str
    code: str
    code_source: str
    message: str
    message_norm: str


def iter_bsl_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and (p.suffix.lower() in BSL_SUFFIXES or p.name == "Module.bsl")
    )


def resolve_bslls_jar(repo_root: Path) -> Path:
    env_path = (os.environ.get("BSLLS_JAR") or "").strip()
    if env_path:
        jar = Path(env_path).expanduser().resolve()
        if jar.is_file():
            return jar
        raise FileNotFoundError(f"BSLLS_JAR does not exist: {jar}")

    default = repo_root / ".nosync/bsl-language-server/build/libs"
    jars = sorted(default.glob("*-exec.jar"))
    if jars:
        return jars[-1]
    raise FileNotFoundError(
        "BSLLS exec.jar not found; set BSLLS_JAR or build .nosync/bsl-language-server"
    )


def normalize_message(message: str) -> str:
    return " ".join(str(message).split())


def _relative_file(path: str | Path, workspace_root: Path) -> str:
    p = Path(path).expanduser().resolve()
    try:
        return p.relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _canonical_rule_name_for_ours(code: str) -> str:
    if code in _CODE_TO_BSLLS_NAME:
        return _CODE_TO_BSLLS_NAME[code]
    return str(RULE_METADATA.get(code, {}).get("name") or code)


def normalize_our_diagnostics(
    diagnostics: list[Diagnostic],
    *,
    workspace_root: Path,
) -> list[NormalizedDiagnostic]:
    rows: list[NormalizedDiagnostic] = []
    for d in diagnostics:
        code = _canonical_rule_name_for_ours(d.code)
        rows.append(
            NormalizedDiagnostic(
                file=_relative_file(d.file, workspace_root),
                line=int(d.line),
                character=int(d.character),
                severity=str(
                    getattr(lsp_compat_severity(d.code, d.severity), "name", d.severity)
                ).upper(),
                code=code,
                code_source=d.code,
                message=d.message,
                message_norm=normalize_message(d.message),
            )
        )
    return sorted(rows, key=lambda row: (row.file, row.line, row.character, row.code))


def normalize_bslls_json_report(
    report: dict[str, Any],
    *,
    workspace_root: Path,
) -> list[NormalizedDiagnostic]:
    rows: list[NormalizedDiagnostic] = []
    for fileinfo in report.get("fileinfos", []):
        raw_path = fileinfo.get("mdoRef") or fileinfo.get("path") or ""
        raw_path = str(raw_path)
        if raw_path.startswith("file://"):
            raw_path = unquote(raw_path[7:])
        file_path = _relative_file(raw_path, workspace_root)
        for diag in fileinfo.get("diagnostics", []):
            rule = str(diag.get("code") or "")
            start = diag.get("range", {}).get("start", {})
            message = str(diag.get("message") or "")
            rows.append(
                NormalizedDiagnostic(
                    file=file_path,
                    line=int(start.get("line", 0)) + 1,
                    character=int(start.get("character", 0)),
                    severity=str(diag.get("severity") or "").upper(),
                    code=rule,
                    code_source=rule,
                    message=message,
                    message_norm=normalize_message(message),
                )
            )
    return sorted(rows, key=lambda row: (row.file, row.line, row.character, row.code))


def diff_diagnostics(
    ours: list[NormalizedDiagnostic],
    bslls: list[NormalizedDiagnostic],
) -> dict[str, Any]:
    ours_by_key = {(d.file, d.line, d.character, d.code): d for d in ours}
    bslls_by_key = {(d.file, d.line, d.character, d.code): d for d in bslls}
    ours_keys = set(ours_by_key)
    bslls_keys = set(bslls_by_key)

    only_ours = [asdict(ours_by_key[key]) for key in sorted(ours_keys - bslls_keys)]
    only_bslls = [asdict(bslls_by_key[key]) for key in sorted(bslls_keys - ours_keys)]

    severity_mismatch: list[dict[str, Any]] = []
    message_mismatch: list[dict[str, Any]] = []
    for key in sorted(ours_keys & bslls_keys):
        our_diag = ours_by_key[key]
        bslls_diag = bslls_by_key[key]
        if our_diag.severity != bslls_diag.severity:
            severity_mismatch.append(
                {
                    "key": list(key),
                    "ours": asdict(our_diag),
                    "bslls": asdict(bslls_diag),
                }
            )
        if our_diag.message_norm != bslls_diag.message_norm:
            message_mismatch.append(
                {
                    "key": list(key),
                    "ours": asdict(our_diag),
                    "bslls": asdict(bslls_diag),
                }
            )

    return {
        "only_ours": only_ours,
        "only_bslls": only_bslls,
        "top_only_ours_codes": Counter(d["code"] for d in only_ours).most_common(10),
        "top_only_bslls_codes": Counter(d["code"] for d in only_bslls).most_common(10),
        "severity_mismatch": severity_mismatch,
        "message_mismatch": message_mismatch,
        "exact_match": not (only_ours or only_bslls or severity_mismatch or message_mismatch),
    }


def _copy_file_preserving_rel(source: Path, root: Path, dest_root: Path) -> Path:
    rel = source.resolve().relative_to(root.resolve())
    dest = dest_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def _copy_related_configuration_context(
    source: Path,
    *,
    workspace_root: Path,
    dest_root: Path,
    copied: set[Path],
) -> None:
    rel = source.resolve().relative_to(workspace_root.resolve())
    parts = rel.parts
    if len(parts) < 2:
        return

    object_name = parts[1]
    object_dir = workspace_root / parts[0] / object_name
    object_xml = workspace_root / parts[0] / f"{object_name}.xml"

    candidates: list[Path] = []
    if object_xml.is_file():
        candidates.append(object_xml)
    if object_dir.is_dir():
        candidates.extend(sorted(object_dir.rglob("*.xml")))

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in copied:
            continue
        _copy_file_preserving_rel(candidate, workspace_root, dest_root)
        copied.add(resolved)


def _copy_root_configuration_context(
    *,
    workspace_root: Path,
    dest_root: Path,
    copied: set[Path],
) -> None:
    for name in ("Configuration.xml", "ConfigDumpInfo.xml"):
        candidate = workspace_root / name
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in copied:
            continue
        _copy_file_preserving_rel(candidate, workspace_root, dest_root)
        copied.add(resolved)


def _run_bslls_analyze(
    *,
    jar_path: Path,
    workspace_root: Path,
    files: list[Path],
    config_path: Path | None,
) -> list[NormalizedDiagnostic]:
    with tempfile.TemporaryDirectory(prefix="bslls-parity-diag-") as tmp:
        tmp_root = Path(tmp)
        src_root = tmp_root / "src"
        out_root = tmp_root / "out"
        src_root.mkdir(parents=True, exist_ok=True)
        out_root.mkdir(parents=True, exist_ok=True)
        copied: set[Path] = set()
        _copy_root_configuration_context(
            workspace_root=workspace_root,
            dest_root=src_root,
            copied=copied,
        )
        for path in files:
            resolved = path.resolve()
            if resolved not in copied:
                _copy_file_preserving_rel(path, workspace_root, src_root)
                copied.add(resolved)
            _copy_related_configuration_context(
                path,
                workspace_root=workspace_root,
                dest_root=src_root,
                copied=copied,
            )

        cmd = [
            "java",
            "-jar",
            str(jar_path),
            "analyze",
            "-s",
            str(src_root),
            "-w",
            str(src_root),
            "-o",
            str(out_root),
            "-r",
            "json",
            "-q",
        ]
        if config_path is not None:
            cmd[3:3] = ["-c", str(config_path)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        report = json.loads((out_root / "bsl-json.json").read_text(encoding="utf-8"))
        return normalize_bslls_json_report(report, workspace_root=src_root)


def _run_bslls_format(
    *,
    jar_path: Path,
    workspace_root: Path,
    files: list[Path],
) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="bslls-parity-format-") as tmp:
        tmp_root = Path(tmp)
        results: dict[str, str] = {}
        for path in files:
            copied = _copy_file_preserving_rel(path, workspace_root, tmp_root)
            subprocess.run(
                ["java", "-jar", str(jar_path), "format", "-s", str(copied), "-q"],
                check=True,
                capture_output=True,
                text=True,
            )
            results[_relative_file(path, workspace_root)] = copied.read_text(encoding="utf-8")
        return results


def compare_with_bslls(
    *,
    workspace_root: Path,
    files: list[Path],
    profile: str,
    config_path: Path | None,
    jar_path: Path,
) -> dict[str, Any]:
    formatter = BslFormatter(profile=profile)

    our_diags: list[Diagnostic] = []
    formatting: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="onec-parity-index-") as tmp:
        idx = SymbolIndex(db_path=str(Path(tmp) / "index.sqlite"))
        indexer = IncrementalIndexer(index=idx, quiet=True)
        for path in files:
            indexer.index_file(str(path))
        engine = DiagnosticEngine(profile=profile, symbol_index=idx)
        for path in files:
            rel = _relative_file(path, workspace_root)
            content = path.read_text(encoding="utf-8", errors="ignore")
            our_diags.extend(engine.check_content(str(path), content, symbol_index=idx))
            formatting[rel] = {"ours": formatter.format(content)}
        idx.close()

    our_diag_norm = normalize_our_diagnostics(our_diags, workspace_root=workspace_root)
    raw_bslls_diags = _run_bslls_analyze(
        jar_path=jar_path,
        workspace_root=workspace_root,
        files=files,
        config_path=config_path,
    )
    bslls_diag_norm = [
        NormalizedDiagnostic(
            file=row.file,
            line=row.line,
            character=row.character,
            severity=row.severity,
            code=row.code,
            code_source=row.code_source,
            message=row.message,
            message_norm=row.message_norm,
        )
        for row in raw_bslls_diags
    ]

    bslls_formatted = _run_bslls_format(
        jar_path=jar_path,
        workspace_root=workspace_root,
        files=files,
    )
    for rel, text in bslls_formatted.items():
        formatting.setdefault(rel, {})
        formatting[rel]["bslls"] = text
        formatting[rel]["match"] = formatting[rel]["ours"] == text

    formatting_diff = [
        {
            "file": rel,
            "match": data.get("match", False),
            "ours_preview": data["ours"][:400],
            "bslls_preview": data["bslls"][:400],
        }
        for rel, data in sorted(formatting.items())
        if not data.get("match", False)
    ]

    diagnostics_diff = diff_diagnostics(our_diag_norm, bslls_diag_norm)
    return {
        "files": [_relative_file(path, workspace_root) for path in files],
        "diagnostics": diagnostics_diff,
        "formatting": {
            "exact_match": not formatting_diff,
            "diffs": formatting_diff,
        },
    }
