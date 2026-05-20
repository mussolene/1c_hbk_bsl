"""Runtime parity helpers for comparing onec-hbk-bsl against Java BSLLS."""

from __future__ import annotations

import hashlib
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
_MIN_BSLLS_JAVA_MAJOR = 17


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
    end_line: int = 0
    end_character: int = 0


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

    cache_dir = Path.home() / ".cache/onec-hbk-bsl/bslls"
    cached_jars = sorted(cache_dir.glob("*-exec.jar"))
    if cached_jars:
        return cached_jars[-1]

    default = repo_root / ".nosync/bsl-language-server/build/libs"
    jars = sorted(default.glob("*-exec.jar"))
    if jars:
        return jars[-1]
    raise FileNotFoundError(
        "BSLLS exec.jar not found; set BSLLS_JAR, download to ~/.cache/onec-hbk-bsl/bslls, "
        "or build .nosync/bsl-language-server"
    )


def _parse_java_major_version(text: str) -> int | None:
    marker = 'version "'
    if marker not in text:
        return None
    raw = text.split(marker, 1)[1].split('"', 1)[0]
    parts = raw.split(".")
    if len(parts) >= 2 and parts[0] == "1":
        token = parts[1]
    else:
        token = parts[0]
    digits = "".join(ch for ch in token if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _java_major_version(java_path: Path) -> int | None:
    proc = subprocess.run(
        [str(java_path), "-version"],
        check=False,
        capture_output=True,
        text=True,
    )
    return _parse_java_major_version(proc.stderr + proc.stdout)


def _candidate_java_paths() -> list[Path]:
    candidates: list[Path] = []

    env_java = (os.environ.get("BSLLS_JAVA") or "").strip()
    if env_java:
        candidates.append(Path(env_java).expanduser())

    java_home = (os.environ.get("JAVA_HOME") or "").strip()
    if java_home:
        candidates.append(Path(java_home).expanduser() / "bin" / "java")

    path_java = shutil.which("java")
    if path_java:
        candidates.append(Path(path_java))

    java_home_cmd = shutil.which("/usr/libexec/java_home") or "/usr/libexec/java_home"
    if Path(java_home_cmd).is_file():
        proc = subprocess.run(
            [java_home_cmd, "-v", str(_MIN_BSLLS_JAVA_MAJOR)],
            check=False,
            capture_output=True,
            text=True,
        )
        home = proc.stdout.strip()
        if proc.returncode == 0 and home:
            candidates.append(Path(home) / "bin" / "java")

    candidates.extend(
        [
            Path("/opt/homebrew/opt/openjdk/bin/java"),
            Path("/opt/homebrew/bin/java"),
            Path("/usr/local/opt/openjdk/bin/java"),
            Path("/usr/local/bin/java"),
        ]
    )

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        try:
            key = resolved.resolve()
        except OSError:
            key = resolved
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def resolve_bslls_java() -> Path:
    checked: list[str] = []
    for candidate in _candidate_java_paths():
        if not candidate.is_file():
            checked.append(f"{candidate}: missing")
            continue
        major = _java_major_version(candidate)
        checked.append(f"{candidate}: {major or 'unknown'}")
        if major is not None and major >= _MIN_BSLLS_JAVA_MAJOR:
            return candidate.resolve()
    raise RuntimeError(
        "BSLLS requires Java 17+; set BSLLS_JAVA or JAVA_HOME to a modern JDK. "
        f"Checked: {', '.join(checked)}"
    )


def normalize_message(message: str) -> str:
    text = " ".join(str(message).split())
    return (
        text.replace("«", '"')
        .replace("»", '"')
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .replace("…", "...")
    )


def _normalize_formatting_for_parity(text: str) -> str:
    """
    Normalize formatting for parity comparison.

    The current parity target intentionally ignores comment-formatting deltas and
    trailing newline differences while still comparing executable code layout
    byte-for-byte.
    """
    out: list[str] = []
    for line in text.rstrip("\n").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            indent = line[: len(line) - len(stripped)]
            out.append(indent + "//")
        else:
            out.append(line)
    return "\n".join(out)


def _character_close_enough(left: int, right: int, *, tolerance: int = 2) -> bool:
    return abs(int(left) - int(right)) <= tolerance


def _near_match_key(diag: NormalizedDiagnostic) -> tuple[str, int, str]:
    return (diag.file, diag.line, diag.code)


def _match_near_diagnostics(
    only_ours: list[NormalizedDiagnostic],
    only_bslls: list[NormalizedDiagnostic],
) -> tuple[
    list[tuple[NormalizedDiagnostic, NormalizedDiagnostic]],
    list[NormalizedDiagnostic],
    list[NormalizedDiagnostic],
]:
    remaining_bslls = list(only_bslls)
    matched: list[tuple[NormalizedDiagnostic, NormalizedDiagnostic]] = []
    unmatched_ours: list[NormalizedDiagnostic] = []

    for our_diag in only_ours:
        want = _near_match_key(our_diag)
        candidate_idx: int | None = None
        best_distance: int | None = None
        for idx, bslls_diag in enumerate(remaining_bslls):
            if _near_match_key(bslls_diag) != want:
                continue
            distance = abs(our_diag.character - bslls_diag.character)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                candidate_idx = idx
        if candidate_idx is None:
            unmatched_ours.append(our_diag)
            continue
        bslls_diag = remaining_bslls[candidate_idx]
        if not _character_close_enough(our_diag.character, bslls_diag.character):
            unmatched_ours.append(our_diag)
            continue
        matched.append((our_diag, bslls_diag))
        remaining_bslls.pop(candidate_idx)

    return matched, unmatched_ours, remaining_bslls


def _relative_file(path: str | Path, workspace_root: Path) -> str:
    p = Path(path).expanduser().resolve()
    try:
        return p.relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _relative_file_many(path: str | Path, *roots: Path) -> str:
    p = Path(path).expanduser().resolve()
    for root in roots:
        try:
            return p.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
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
                end_line=int(d.end_line),
                end_character=int(d.end_character),
                severity=str(
                    getattr(lsp_compat_severity(d.code, d.severity), "name", d.severity)
                ).upper(),
                code=code,
                code_source=d.code,
                message=d.message,
                message_norm=normalize_message(d.message),
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            row.file,
            row.line,
            row.character,
            row.end_line,
            row.end_character,
            row.code,
        ),
    )


def normalize_bslls_json_report(
    report: dict[str, Any],
    *,
    workspace_root: Path,
    extra_roots: tuple[Path, ...] = (),
) -> list[NormalizedDiagnostic]:
    rows: list[NormalizedDiagnostic] = []
    for fileinfo in report.get("fileinfos", []):
        raw_path = fileinfo.get("path") or fileinfo.get("mdoRef") or ""
        raw_path = str(raw_path)
        if raw_path.startswith("file://"):
            raw_path = unquote(raw_path[7:])
        file_path = _relative_file_many(raw_path, workspace_root, *extra_roots)
        for diag in fileinfo.get("diagnostics", []):
            rule = str(diag.get("code") or "")
            start = diag.get("range", {}).get("start", {})
            message = str(diag.get("message") or "")
            rows.append(
                NormalizedDiagnostic(
                    file=file_path,
                    line=int(start.get("line", 0)) + 1,
                    character=int(start.get("character", 0)),
                    end_line=int(diag.get("range", {}).get("end", {}).get("line", 0)) + 1,
                    end_character=int(diag.get("range", {}).get("end", {}).get("character", 0)),
                    severity=str(diag.get("severity") or "").upper(),
                    code=rule,
                    code_source=rule,
                    message=message,
                    message_norm=normalize_message(message),
                )
            )
    return sorted(
        rows,
        key=lambda row: (
            row.file,
            row.line,
            row.character,
            row.end_line,
            row.end_character,
            row.code,
        ),
    )


def diff_diagnostics(
    ours: list[NormalizedDiagnostic],
    bslls: list[NormalizedDiagnostic],
) -> dict[str, Any]:
    def identity_key(
        diag: NormalizedDiagnostic,
    ) -> tuple[str, int, int, int, int, str] | tuple[str, int, int, int, int, str, str]:
        base = (
            diag.file,
            diag.line,
            diag.character,
            diag.end_line,
            diag.end_character,
            diag.code,
        )
        if diag.code == "Typo":
            return (*base, diag.message_norm)
        return base

    ours_by_key = {identity_key(d): d for d in ours}
    bslls_by_key = {identity_key(d): d for d in bslls}
    ours_keys = set(ours_by_key)
    bslls_keys = set(bslls_by_key)

    only_ours_rows = [ours_by_key[key] for key in sorted(ours_keys - bslls_keys)]
    only_bslls_rows = [bslls_by_key[key] for key in sorted(bslls_keys - ours_keys)]

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

    near_pairs, unmatched_only_ours, unmatched_only_bslls = _match_near_diagnostics(
        only_ours_rows,
        only_bslls_rows,
    )
    anchor_mismatch: list[dict[str, Any]] = []
    anchor_and_severity_mismatch: list[dict[str, Any]] = []
    anchor_and_message_mismatch: list[dict[str, Any]] = []
    anchor_message_severity_mismatch: list[dict[str, Any]] = []
    for our_diag, bslls_diag in near_pairs:
        record = {
            "ours": asdict(our_diag),
            "bslls": asdict(bslls_diag),
            "character_delta": int(our_diag.character) - int(bslls_diag.character),
        }
        same_severity = our_diag.severity == bslls_diag.severity
        same_message = our_diag.message_norm == bslls_diag.message_norm
        if same_severity and same_message:
            anchor_mismatch.append(record)
        elif (not same_severity) and same_message:
            anchor_and_severity_mismatch.append(record)
        elif same_severity and (not same_message):
            anchor_and_message_mismatch.append(record)
        else:
            anchor_message_severity_mismatch.append(record)

    only_ours = [asdict(row) for row in unmatched_only_ours]
    only_bslls = [asdict(row) for row in unmatched_only_bslls]

    return {
        "only_ours": only_ours,
        "only_bslls": only_bslls,
        "top_only_ours_codes": Counter(d["code"] for d in only_ours).most_common(10),
        "top_only_bslls_codes": Counter(d["code"] for d in only_bslls).most_common(10),
        "severity_mismatch": severity_mismatch,
        "message_mismatch": message_mismatch,
        "anchor_mismatch": anchor_mismatch,
        "anchor_and_severity_mismatch": anchor_and_severity_mismatch,
        "anchor_and_message_mismatch": anchor_and_message_mismatch,
        "anchor_message_severity_mismatch": anchor_message_severity_mismatch,
        "near_match": not (
            only_ours
            or only_bslls
            or severity_mismatch
            or message_mismatch
            or anchor_mismatch
            or anchor_and_severity_mismatch
            or anchor_and_message_mismatch
            or anchor_message_severity_mismatch
        ),
        "exact_match": not (
            only_ours
            or only_bslls
            or severity_mismatch
            or message_mismatch
            or anchor_mismatch
            or anchor_and_severity_mismatch
            or anchor_and_message_mismatch
            or anchor_message_severity_mismatch
        ),
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


def _copy_full_metadata_xml_tree(
    *,
    workspace_root: Path,
    dest_root: Path,
    copied: set[Path],
) -> None:
    for candidate in workspace_root.rglob("*.xml"):
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
    java_path = resolve_bslls_java()
    with tempfile.TemporaryDirectory(prefix="bslls-parity-diag-") as tmp:
        tmp_root = Path(tmp)
        src_root = tmp_root / "src"
        out_root = tmp_root / "out"
        src_root.mkdir(parents=True, exist_ok=True)
        out_root.mkdir(parents=True, exist_ok=True)
        copied: set[Path] = set()
        _copy_full_metadata_xml_tree(
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
            str(java_path),
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
            cmd[4:4] = ["-c", str(config_path)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        report = json.loads((out_root / "bsl-json.json").read_text(encoding="utf-8"))
        return normalize_bslls_json_report(
            report,
            workspace_root=workspace_root,
            extra_roots=(src_root, Path.cwd()),
        )


def _run_bslls_format(
    *,
    jar_path: Path,
    workspace_root: Path,
    files: list[Path],
) -> dict[str, str]:
    java_path = resolve_bslls_java()
    with tempfile.TemporaryDirectory(prefix="bslls-parity-format-") as tmp:
        tmp_root = Path(tmp)
        for path in files:
            _copy_file_preserving_rel(path, workspace_root, tmp_root)
        subprocess.run(
            [str(java_path), "-jar", str(jar_path), "format", "-s", str(tmp_root), "-q"],
            check=True,
            capture_output=True,
            text=True,
        )
        return {
            _relative_file(path, workspace_root): (
                tmp_root / path.resolve().relative_to(workspace_root.resolve())
            ).read_text(encoding="utf-8")
            for path in files
        }


def compute_baseline_fingerprint(
    *,
    workspace_root: Path,
    files: list[Path],
    jar_path: Path,
    config_path: Path | None,
) -> str:
    payload = {
        "workspace_root": str(workspace_root.resolve()),
        "jar_path": str(jar_path.resolve()),
        "config_path": str(config_path.resolve()) if config_path is not None else None,
        "files": [
            {
                "path": _relative_file(path, workspace_root),
                "size": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in files
        ],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def capture_bslls_baseline(
    *,
    workspace_root: Path,
    files: list[Path],
    config_path: Path | None,
    jar_path: Path,
) -> dict[str, Any]:
    normalized_diags = _run_bslls_analyze(
        jar_path=jar_path,
        workspace_root=workspace_root,
        files=files,
        config_path=config_path,
    )
    formatted = _run_bslls_format(
        jar_path=jar_path,
        workspace_root=workspace_root,
        files=files,
    )
    return {
        "fingerprint": compute_baseline_fingerprint(
            workspace_root=workspace_root,
            files=files,
            jar_path=jar_path,
            config_path=config_path,
        ),
        "workspace_root": str(workspace_root.resolve()),
        "jar_path": str(jar_path.resolve()),
        "config_path": str(config_path.resolve()) if config_path is not None else None,
        "files": [_relative_file(path, workspace_root) for path in files],
        "diagnostics": [asdict(row) for row in normalized_diags],
        "formatting": formatted,
    }


def compare_with_bslls_baseline(
    *,
    workspace_root: Path,
    files: list[Path],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    formatter = BslFormatter()

    our_diags: list[Diagnostic] = []
    formatting: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="onec-parity-index-") as tmp:
        idx = SymbolIndex(db_path=str(Path(tmp) / "index.sqlite"))
        indexer = IncrementalIndexer(index=idx, quiet=True)
        indexer.index_metadata(str(workspace_root))
        for path in files:
            indexer.index_file(str(path))
        engine = DiagnosticEngine(symbol_index=idx)
        for path in files:
            rel = _relative_file(path, workspace_root)
            content = path.read_text(encoding="utf-8", errors="ignore")
            diags = [
                d
                for d in engine.check_content(str(path), content, symbol_index=idx)
                if engine._rule_enabled(d.code)
            ]
            our_diags.extend(diags)
            formatting[rel] = {"ours": formatter.format(content)}
        idx.close()

    our_diag_norm = normalize_our_diagnostics(our_diags, workspace_root=workspace_root)
    bslls_diag_norm = [NormalizedDiagnostic(**row) for row in baseline.get("diagnostics", [])]

    bslls_formatted = {
        str(rel): str(text) for rel, text in dict(baseline.get("formatting", {})).items()
    }
    for rel, text in bslls_formatted.items():
        formatting.setdefault(rel, {})
        formatting[rel]["bslls"] = text
        formatting[rel]["ours_norm"] = _normalize_formatting_for_parity(formatting[rel]["ours"])
        formatting[rel]["bslls_norm"] = _normalize_formatting_for_parity(text)
        formatting[rel]["match"] = formatting[rel]["ours_norm"] == formatting[rel]["bslls_norm"]

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


def compare_with_bslls(
    *,
    workspace_root: Path,
    files: list[Path],
    config_path: Path | None,
    jar_path: Path,
) -> dict[str, Any]:
    baseline = capture_bslls_baseline(
        jar_path=jar_path,
        workspace_root=workspace_root,
        files=files,
        config_path=config_path,
    )
    return compare_with_bslls_baseline(
        workspace_root=workspace_root,
        files=files,
        baseline=baseline,
    )
