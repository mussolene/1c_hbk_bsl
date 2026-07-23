#!/usr/bin/env python3
"""Compare onec-hbk-bsl CLI JSON with BSLLS ``analyze`` JSON.

This is a development-only parity helper that implements the rule-contract
parity procedure: onec runs with exact ``--select`` JSON output, BSLLS runs
with ``diagnostics.mode=ONLY`` for the compatible rule names, both tools analyze
the same temporary file set, and coordinates are normalized before comparison.

The deterministic report preserves multiplicity and classifies exact,
same-start statement, same-line, range-only, semantic, duplicate, and
unmappable results. Exit status is 0 for parity, 1 for comparable deltas, 2 for
tool/mapping failure, and 3 for invalid CLI input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onec_hbk_bsl.analysis.diagnostics import (  # noqa: E402
    RULE_METADATA,
    DiagnosticEngine,
    resolve_rule_token_to_code,
)

INDEXED_ONEC_RULES = frozenset({"BSL176", "BSL254"})


@dataclass(frozen=True, order=True)
class DiagnosticKey:
    file_key: str
    line: int
    character: int
    end_line: int
    end_character: int
    code: str


@dataclass(frozen=True, order=True)
class UnmappableDiagnostic:
    side: str
    ordinal: int
    code: str
    reason: str


@dataclass(frozen=True)
class ParsedDiagnostics:
    counts: Counter[DiagnosticKey]
    unmappable: tuple[UnmappableDiagnostic, ...] = ()


@dataclass(frozen=True)
class Comparison:
    exact: int
    statement: int
    line: int
    only_onec: Counter[DiagnosticKey]
    only_bslls: Counter[DiagnosticKey]
    duplicate_onec: int
    duplicate_bslls: int
    duplicate_common: int
    duplicate_delta: int

    @property
    def range_only(self) -> int:
        return self.statement + self.line

    @property
    def has_deltas(self) -> bool:
        return bool(self.only_onec or self.only_bslls or self.range_only or self.duplicate_delta)


def normalize_rule_codes(raw: str) -> frozenset[str]:
    codes: set[str] = set()
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        code = resolve_rule_token_to_code(token) or token.upper()
        codes.add(code)
    if not codes:
        raise ValueError("--select must contain at least one rule code or BSLLS name")
    return frozenset(codes)


def bslls_rule_name(code: str) -> str:
    metadata = RULE_METADATA.get(code)
    if not metadata:
        raise ValueError(f"unknown diagnostic code: {code}")
    name = str(metadata.get("name", "")).strip()
    if not name:
        raise ValueError(f"diagnostic has no BSLLS-compatible name: {code}")
    return name


def find_bslls_jar(repo_root: Path, explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = explicit.expanduser()
        return candidate.resolve() if candidate.is_file() else None
    env = os.environ.get("BSLLS_JAR", "").strip()
    if env:
        candidate = Path(env).expanduser()
        return candidate.resolve() if candidate.is_file() else None

    candidates = [
        *list((repo_root / ".nosync" / "bsl-language-server").glob("**/*-exec.jar")),
        *list(Path.home().glob(".cache/onec-hbk-bsl/bslls/bsl-language-server*-exec.jar")),
    ]
    for candidate in sorted(candidates, key=_bslls_jar_sort_key, reverse=True):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _bslls_jar_sort_key(path: Path) -> tuple[tuple[int, ...], float, str]:
    match = re.search(r"bsl-language-server-(\d+(?:\.\d+)*)-exec\.jar$", path.name)
    version = tuple(int(part) for part in match.group(1).split(".")) if match else ()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return version, mtime, path.as_posix()


def _relative_file_key(path: Path, workspace: Path) -> str | None:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return None


def _path_from_uri_or_text(value: str) -> Path | None:
    if not value:
        return None
    if value.startswith("file://"):
        parsed = urlparse(value)
        return Path(unquote(parsed.path))
    return Path(value)


_EDT_ROOT_DIRS: frozenset[str] = frozenset(
    {
        "AccountingRegisters",
        "AccumulationRegisters",
        "BusinessProcesses",
        "Catalogs",
        "ChartsOfAccounts",
        "ChartsOfCalculationTypes",
        "ChartsOfCharacteristicTypes",
        "CommonCommands",
        "CommonForms",
        "CommonModules",
        "Constants",
        "DataProcessors",
        "DefinedTypes",
        "DocumentJournals",
        "Documents",
        "Enums",
        "ExchangePlans",
        "ExternalDataSources",
        "InformationRegisters",
        "Reports",
        "Roles",
        "ScheduledJobs",
        "Sequences",
        "SessionParameters",
        "SettingsStorages",
        "Subsystems",
        "Tasks",
        "WebServices",
        "XDTOPackages",
    }
)


def _metadata_suffix(path: Path) -> str | None:
    parts = path.parts
    for index, part in enumerate(parts):
        if part in _EDT_ROOT_DIRS:
            return Path(*parts[index:]).as_posix()
    for index, part in enumerate(parts):
        if part == "Ext":
            return Path(*parts[index:]).as_posix()
    return None


def _mapped_file_key(value: str, source_root: Path, workspace: Path) -> str | None:
    path = _path_from_uri_or_text(value)
    if path is None:
        return None
    if not path.is_absolute():
        if ".." in path.parts:
            return None
        return path.as_posix().lstrip("./")
    for root in (source_root, workspace):
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return _metadata_suffix(path)


def _bslls_file_key(fileinfo: dict, source_root: Path, workspace: Path) -> str | None:
    for field in ("mdoRef", "path"):
        value = str(fileinfo.get(field, ""))
        if not value:
            continue
        file_key = _mapped_file_key(value, source_root, workspace)
        if file_key is not None:
            return file_key
    return None


def _related_information_uri(item: dict) -> str | None:
    for related in item.get("relatedInformation", []) or []:
        location = related.get("location", {}) if isinstance(related, dict) else {}
        value = location.get("uri") or related.get("uri")
        if value:
            return str(value)
    return None


def _bslls_diagnostic_file_key(
    item: dict,
    fileinfo: dict,
    source_root: Path,
    workspace: Path,
) -> tuple[str | None, str]:
    related_uri = _related_information_uri(item)
    if related_uri is not None:
        return (
            _mapped_file_key(related_uri, source_root, workspace),
            "relatedInformation URI is outside allowed roots",
        )
    return (
        _bslls_file_key(fileinfo, source_root, workspace),
        "fileinfo path is outside allowed roots",
    )


def _normalized_code(item: dict) -> str:
    raw_code = str(item.get("code", "")).strip()
    return resolve_rule_token_to_code(raw_code) or raw_code.upper()


def onec_keys(raw: list[dict], workspace: Path, select: frozenset[str]) -> ParsedDiagnostics:
    keys: Counter[DiagnosticKey] = Counter()
    unmappable: list[UnmappableDiagnostic] = []
    ordinal = 0
    for item in raw:
        code = _normalized_code(item)
        if code not in select:
            continue
        ordinal += 1
        file_key = _mapped_file_key(str(item.get("file", "")), workspace, workspace)
        if file_key is None:
            unmappable.append(
                UnmappableDiagnostic("onec", ordinal, code, "file is outside allowed roots")
            )
            continue
        keys[
            DiagnosticKey(
                file_key=file_key,
                line=int(item.get("line", 0)),
                character=int(item.get("character", 0)),
                end_line=int(item.get("end_line", item.get("line", 0))),
                end_character=int(item.get("end_character", item.get("character", 0))),
                code=code,
            )
        ] += 1
    return ParsedDiagnostics(keys, tuple(unmappable))


def bslls_keys(
    raw: dict, source_root: Path, workspace: Path, select: frozenset[str]
) -> ParsedDiagnostics:
    keys: Counter[DiagnosticKey] = Counter()
    unmappable: list[UnmappableDiagnostic] = []
    ordinal = 0
    for fileinfo in raw.get("fileinfos", []):
        for item in fileinfo.get("diagnostics", []):
            code = _normalized_code(item)
            if code not in select:
                continue
            ordinal += 1
            file_key, reason = _bslls_diagnostic_file_key(item, fileinfo, source_root, workspace)
            if file_key is None:
                unmappable.append(UnmappableDiagnostic("bslls", ordinal, code, reason))
                continue
            diagnostic_range = item.get("range", {})
            start = diagnostic_range.get("start", {})
            end = diagnostic_range.get("end", {})
            keys[
                DiagnosticKey(
                    file_key=file_key,
                    line=int(start.get("line", 0)) + 1,
                    character=int(start.get("character", 0)),
                    end_line=int(end.get("line", 0)) + 1,
                    end_character=int(end.get("character", 0)),
                    code=code,
                )
            ] += 1
    return ParsedDiagnostics(keys, tuple(unmappable))


def _duplicates(values: Counter[DiagnosticKey]) -> Counter[DiagnosticKey]:
    return Counter({key: count - 1 for key, count in values.items() if count > 1})


def _consume_projected_pairs(
    ours: Counter[DiagnosticKey],
    theirs: Counter[DiagnosticKey],
    projection,
) -> int:
    ours_groups: dict[tuple, list[DiagnosticKey]] = {}
    theirs_groups: dict[tuple, list[DiagnosticKey]] = {}
    for key in ours:
        ours_groups.setdefault(projection(key), []).append(key)
    for key in theirs:
        theirs_groups.setdefault(projection(key), []).append(key)

    matched = 0
    for projected in sorted(set(ours_groups) & set(theirs_groups)):
        ours_keys = sorted(ours_groups[projected])
        theirs_keys = sorted(theirs_groups[projected])
        remaining = min(
            sum(ours[key] for key in ours_keys),
            sum(theirs[key] for key in theirs_keys),
        )
        matched += remaining
        for values, keys in ((ours, ours_keys), (theirs, theirs_keys)):
            to_consume = remaining
            for key in keys:
                consumed = min(values[key], to_consume)
                values[key] -= consumed
                to_consume -= consumed
                if values[key] == 0:
                    del values[key]
                if to_consume == 0:
                    break
    return matched


def compare_diagnostics(ours: Counter[DiagnosticKey], theirs: Counter[DiagnosticKey]) -> Comparison:
    ours_duplicates = _duplicates(ours)
    theirs_duplicates = _duplicates(theirs)
    remaining_ours = Counter({key: 1 for key in ours})
    remaining_theirs = Counter({key: 1 for key in theirs})
    exact_counter = remaining_ours & remaining_theirs
    exact = exact_counter.total()
    remaining_ours -= exact_counter
    remaining_theirs -= exact_counter
    statement = _consume_projected_pairs(
        remaining_ours,
        remaining_theirs,
        lambda key: (key.file_key, key.code, key.line, key.character),
    )
    line = _consume_projected_pairs(
        remaining_ours,
        remaining_theirs,
        lambda key: (key.file_key, key.code, key.line),
    )
    duplicate_common = (ours_duplicates & theirs_duplicates).total()
    duplicate_onec = ours_duplicates.total()
    duplicate_bslls = theirs_duplicates.total()
    return Comparison(
        exact=exact,
        statement=statement,
        line=line,
        only_onec=remaining_ours,
        only_bslls=remaining_theirs,
        duplicate_onec=duplicate_onec,
        duplicate_bslls=duplicate_bslls,
        duplicate_common=duplicate_common,
        duplicate_delta=(
            (ours_duplicates - theirs_duplicates).total()
            + (theirs_duplicates - ours_duplicates).total()
        ),
    )


def _selected_files(workspace: Path, paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = raw_path if raw_path.is_absolute() else workspace / raw_path
        if path.is_file() and path.suffix.lower() == ".bsl":
            files.append(path.resolve())
            continue
        if path.is_dir():
            files.extend(sorted(p.resolve() for p in path.rglob("*.bsl") if p.is_file()))
            continue
        raise FileNotFoundError(f"not a .bsl file or directory: {raw_path}")
    return sorted(set(files))


def _copy_inputs(files: list[Path], workspace: Path, source_root: Path) -> list[Path]:
    copied: list[Path] = []
    for path in files:
        file_key = _relative_file_key(path, workspace)
        if file_key is None:
            raise ValueError("selected input is outside workspace")
        rel = Path(file_key)
        destination = source_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(destination)
    return copied


def run_onec_cli(
    files: list[Path],
    scratch_dir: Path,
    select: frozenset[str],
    *,
    jobs: str,
    timeout: int,
) -> list[dict]:
    paths_file = scratch_dir / "onec-paths.txt"
    paths_file.write_text(
        "".join(f"{path}\n" for path in files),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "onec_hbk_bsl",
        "check",
        "--no-config",
        "--format",
        "json",
        "--select",
        ",".join(sorted(select)),
        "--exit-zero",
        "--jobs",
        jobs,
        "--paths-from",
        str(paths_file),
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError("onec-hbk-bsl check failed")
    return json.loads(result.stdout)


def run_onec_indexed_engine(
    files: list[Path],
    scratch_dir: Path,
    select: frozenset[str],
    source_root: Path,
) -> list[dict]:
    from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
    from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

    index_path = scratch_dir / "onec-index.sqlite"
    index = SymbolIndex(db_path=str(index_path))
    indexer = IncrementalIndexer(index=index, quiet=True)
    try:
        if "BSL176" in select:
            indexer.index_metadata(str(source_root))
        for path in files:
            indexer.index_file(str(path))
        engine = DiagnosticEngine(select=set(select), symbol_index=index)
        diagnostics = []
        for path in files:
            diagnostics.extend(engine.check_file(str(path)))
        return [diag.to_dict(include_rule_name=True) for diag in diagnostics]
    finally:
        index.close()


def _write_bslls_config(path: Path, select: frozenset[str]) -> None:
    parameters = {bslls_rule_name(code): True for code in sorted(select)}
    payload = {
        "language": "en",
        "diagnostics": {
            "mode": "ONLY",
            "parameters": parameters,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_bslls(
    jar: Path,
    source_root: Path,
    output_dir: Path,
    config_path: Path,
    *,
    timeout: int,
) -> dict:
    java = os.environ.get("BSLLS_JAVA", "java")
    command = [
        java,
        "-jar",
        str(jar),
        "analyze",
        "--silent",
        "--configuration",
        str(config_path),
        "--srcDir",
        str(source_root),
        "--workspaceDir",
        str(source_root),
        "--outputDir",
        str(output_dir),
        "--reporter",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError("BSLLS analyze failed")
    json_path = output_dir / "bsl-json.json"
    if not json_path.is_file():
        raise RuntimeError("BSLLS did not produce bsl-json.json")
    return json.loads(json_path.read_text(encoding="utf-8"))


def bslls_file_set(raw: dict, source_root: Path) -> tuple[set[str], int]:
    result: set[str] = set()
    unmappable = 0
    for fileinfo in raw.get("fileinfos", []):
        file_key = _bslls_file_key(fileinfo, source_root, source_root)
        if file_key is None:
            unmappable += 1
        else:
            result.add(file_key)
    return result, unmappable


def _serialized_keys(values: Counter[DiagnosticKey], *, limit: int) -> list[dict]:
    return [
        {
            "file_key": value.file_key,
            "line": value.line,
            "character": value.character,
            "end_line": value.end_line,
            "end_character": value.end_character,
            "code": value.code,
            "count": count,
        }
        for value, count in sorted(values.items())[:limit]
    ]


def _serialized_unmappable(values: tuple[UnmappableDiagnostic, ...]) -> list[dict]:
    return [
        {
            "side": value.side,
            "ordinal": value.ordinal,
            "code": value.code,
            "reason": value.reason,
        }
        for value in values
    ]


def _counts_by_code(values: Counter[DiagnosticKey]) -> dict[str, int]:
    by_code = Counter()
    for value, count in values.items():
        by_code[value.code] += count
    return dict(sorted(by_code.items()))


def _report_payload(
    *,
    select: frozenset[str],
    file_count: int,
    ours: ParsedDiagnostics,
    theirs: ParsedDiagnostics,
    comparison: Comparison,
    limit: int,
) -> dict:
    unmappable = tuple(sorted((*ours.unmappable, *theirs.unmappable)))
    return {
        "selected": sorted(select),
        "files": file_count,
        "counts": {
            "onec": ours.counts.total(),
            "bslls": theirs.counts.total(),
            "exact": comparison.exact,
            "statement": comparison.statement,
            "line": comparison.line,
            "range_only": comparison.range_only,
            "duplicate_onec": comparison.duplicate_onec,
            "duplicate_bslls": comparison.duplicate_bslls,
            "duplicate_common": comparison.duplicate_common,
            "duplicate_delta": comparison.duplicate_delta,
            "only_onec": comparison.only_onec.total(),
            "only_bslls": comparison.only_bslls.total(),
            "semantic_onec": comparison.only_onec.total(),
            "semantic_bslls": comparison.only_bslls.total(),
            "unmappable": len(unmappable),
        },
        "only_onec": _serialized_keys(comparison.only_onec, limit=limit),
        "only_onec_by_code": _counts_by_code(comparison.only_onec),
        "only_bslls": _serialized_keys(comparison.only_bslls, limit=limit),
        "only_bslls_by_code": _counts_by_code(comparison.only_bslls),
        "unmappable": _serialized_unmappable(unmappable),
    }


def _print_report(payload: dict, *, output_format: str, limit: int) -> None:
    if output_format == "json":
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    counts = payload["counts"]
    print(f"selected: {','.join(payload['selected'])}")
    print(f"files: {payload['files']}")
    for label in (
        "onec",
        "bslls",
        "exact",
        "statement",
        "line",
        "range_only",
        "duplicate_onec",
        "duplicate_bslls",
        "duplicate_common",
        "duplicate_delta",
        "semantic_onec",
        "semantic_bslls",
        "only_onec",
        "only_bslls",
        "unmappable",
    ):
        print(f"{label}: {counts[label]}")

    for label in ("only_bslls", "only_onec"):
        by_code = payload[f"{label}_by_code"]
        if by_code:
            print(
                f"{label}_by_code: "
                + ", ".join(f"{code}={count}" for code, count in by_code.items())
            )
        for value in payload[label][:limit]:
            print(
                "  "
                f"{value['file_key']}:{value['line']}:{value['character']}-"
                f"{value['end_line']}:{value['end_character']} "
                f"{value['code']} x{value['count']}"
            )
    for value in payload["unmappable"]:
        print(f"  unmappable {value['side']}#{value['ordinal']} {value['code']} {value['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, help=".bsl files or directories under workspace"
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--select", required=True, help="Comma-separated BSL### or BSLLS rule names"
    )
    parser.add_argument("--jar", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--limit", type=int, default=30, help="Maximum deltas printed per side")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--onec-json",
        type=Path,
        help="Use captured onec JSON instead of executing analyzers (requires --bslls-json).",
    )
    parser.add_argument(
        "--bslls-json",
        type=Path,
        help="Use captured BSLLS JSON instead of executing analyzers (requires --onec-json).",
    )
    parser.add_argument("--jobs", default="1", help="onec-hbk-bsl worker jobs (default: 1)")
    parser.add_argument("--timeout", type=int, default=240, help="Per-tool timeout in seconds")
    parser.add_argument(
        "--preserve-source-root",
        action="store_true",
        help="Run against the original workspace/source root instead of a temp .bsl copy.",
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    select = normalize_rule_codes(args.select)
    captured_mode = args.onec_json is not None or args.bslls_json is not None
    if captured_mode and (args.onec_json is None or args.bslls_json is None):
        print("--onec-json and --bslls-json must be provided together.", file=sys.stderr)
        return 3

    if captured_mode:
        try:
            onec_raw = json.loads(args.onec_json.read_text(encoding="utf-8"))
            raw = json.loads(args.bslls_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print("Unable to read captured JSON.", file=sys.stderr)
            return 2
        files: list[Path] = []
        source_root = workspace
    else:
        jar = find_bslls_jar(args.repo_root.resolve(), args.jar)
        if jar is None:
            print(
                "SKIP: no BSLLS jar found (use --jar, BSLLS_JAR, .nosync, or user cache).",
                file=sys.stderr,
            )
            return 2
        try:
            files = _selected_files(workspace, args.paths)
        except (FileNotFoundError, ValueError):
            print("Invalid .bsl input selection.", file=sys.stderr)
            return 3
        if not files:
            print("No .bsl files selected.", file=sys.stderr)
            return 3

        try:
            with tempfile.TemporaryDirectory(prefix="bslls-parity-") as td:
                temp_root = Path(td)
                source_root = workspace if args.preserve_source_root else temp_root / "src"
                output_dir = Path(td) / "out"
                config_path = Path(td) / "bslls-only.json"
                source_root.mkdir(parents=True, exist_ok=True)
                output_dir.mkdir()
                copied = (
                    files
                    if args.preserve_source_root
                    else _copy_inputs(files, workspace, source_root)
                )
                _write_bslls_config(config_path, select)
                if select & INDEXED_ONEC_RULES:
                    onec_raw = run_onec_indexed_engine(copied, temp_root, select, source_root)
                else:
                    onec_raw = run_onec_cli(
                        copied,
                        temp_root,
                        select,
                        jobs=args.jobs,
                        timeout=args.timeout,
                    )
                raw = run_bslls(jar, source_root, output_dir, config_path, timeout=args.timeout)
                expected_files = {
                    file_key
                    for path in copied
                    if (file_key := _relative_file_key(path, source_root)) is not None
                }
                actual_files, unmappable_files = bslls_file_set(raw, source_root)
                if unmappable_files or actual_files != expected_files:
                    missing = sorted(expected_files - actual_files)
                    extra = sorted(actual_files - expected_files)
                    raise RuntimeError(
                        "BSLLS analyzed a different file set: "
                        f"missing={missing[:10]} extra={extra[:10]} "
                        f"unmappable={unmappable_files}"
                    )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except Exception:  # noqa: BLE001 - sanitized CLI boundary
            print("Parity execution failed.", file=sys.stderr)
            return 2

    ours = onec_keys(onec_raw, source_root, select)
    theirs = bslls_keys(raw, source_root, source_root, select)
    comparison = compare_diagnostics(ours.counts, theirs.counts)
    mapped_files = {key.file_key for key in (*ours.counts.keys(), *theirs.counts.keys())}
    payload = _report_payload(
        select=select,
        file_count=len(files) if files else len(mapped_files),
        ours=ours,
        theirs=theirs,
        comparison=comparison,
        limit=args.limit,
    )
    _print_report(payload, output_format=args.format, limit=args.limit)

    if ours.unmappable or theirs.unmappable:
        return 2
    if comparison.has_deltas:
        return 1
    if args.format == "text":
        print("OK: selected diagnostics match by file, range, code, and multiplicity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
