#!/usr/bin/env python3
"""Deterministic source and artifact-first release verification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("darwin-arm64", "darwin-x64", "linux-x64", "win32-x64")


def _load_quality_config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["tool"]["onec_hbk_bsl"]["quality"]


def _percent(covered: int, statements: int) -> float:
    return 100.0 if statements == 0 else covered * 100.0 / statements


def verify_coverage(
    coverage_path: Path,
    *,
    changed_lines: dict[str, set[int]] | None = None,
) -> dict[str, float]:
    data = json.loads(coverage_path.read_text(encoding="utf-8"))
    config = _load_quality_config()
    files = data["files"]
    results = {"total": float(data["totals"]["percent_covered"])}

    failures: list[str] = []
    total_floor = float(config["total"])
    if results["total"] < total_floor:
        failures.append(f"total {results['total']:.2f}% < {total_floor:.2f}%")

    for name, component in config["components"].items():
        prefix = str(component["prefix"])
        summaries = [row["summary"] for path, row in files.items() if path.startswith(prefix)]
        statements = sum(int(row["num_statements"]) for row in summaries)
        covered = sum(int(row["covered_lines"]) for row in summaries)
        value = _percent(covered, statements)
        results[name] = value
        floor = float(component["floor"])
        if value < floor:
            failures.append(f"{name} {value:.2f}% < {floor:.2f}%")

    if changed_lines is not None:
        executable = 0
        covered = 0
        for path, lines in changed_lines.items():
            row = files.get(path)
            if row is None:
                continue
            executed = set(row.get("executed_lines", ()))
            missing = set(row.get("missing_lines", ()))
            relevant = lines & (executed | missing)
            executable += len(relevant)
            covered += len(relevant & executed)
        diff_value = _percent(covered, executable)
        results["diff"] = diff_value
        diff_floor = float(config["diff"])
        if diff_value < diff_floor:
            failures.append(f"diff {diff_value:.2f}% < {diff_floor:.2f}%")

    if failures:
        raise ValueError("coverage gate failed: " + "; ".join(failures))
    return results


def changed_python_lines(base: str) -> dict[str, set[int]]:
    result = subprocess.run(
        ["git", "diff", "--unified=0", base, "--", "src/onec_hbk_bsl"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changed.setdefault(current, set())
            continue
        if current is None or not line.startswith("@@"):
            continue
        match = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if match:
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            changed[current].update(range(start, start + count))
    return changed


def source_contract() -> dict[str, Any]:
    from onec_hbk_bsl import __version__
    from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.runner import (
        DIAGNOSTIC_RUNTIME_RULE_CODES,
    )
    from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule
    from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA
    from onec_hbk_bsl.analysis.platform_api import get_platform_api

    api = get_platform_api()
    rules = sorted(RULE_METADATA)
    runtime_rules = sorted(DIAGNOSTIC_RUNTIME_RULE_CODES)
    if len(rules) != 180 or rules != runtime_rules:
        raise ValueError("diagnostic catalog/runtime contract must contain the same 180 rules")
    leaked = [code for code in rules if "%s" in get_rule(code).message]
    if leaked:
        raise ValueError(f"unrendered diagnostic placeholders: {', '.join(leaked)}")
    return {
        "version": __version__,
        "rules": rules,
        "runtime_rules": runtime_rules,
        "platform_api": {
            "types": sorted(api._types),  # noqa: SLF001 - internal release contract
            "globals": sorted(item.name for item in api._globals),  # noqa: SLF001
            "methods": sorted(
                f"{type_name}.{method.name}"
                for type_name, api_type in api._types.items()  # noqa: SLF001
                for method in api_type.methods
            ),
        },
    }


def verify_generated_docs() -> None:
    script = ROOT / "scripts" / "build_diagnostic_rules_doc.py"
    spec = importlib.util.spec_from_file_location("build_diagnostic_rules_doc", script)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load diagnostic rules documentation builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = module.build_markdown()
    actual = (ROOT / "docs" / "diagnostic-rules.md").read_text(encoding="utf-8")
    if actual != expected:
        raise ValueError("docs/diagnostic-rules.md is stale")


def _job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    if match is None:
        raise ValueError(f"release workflow is missing job {job}")
    return match.group("body")


def verify_release_dag(workflow_path: Path | None = None) -> None:
    path = workflow_path or ROOT / ".github" / "workflows" / "release.yml"
    workflow = path.read_text(encoding="utf-8")
    preflight = _job_block(workflow, "preflight")
    for dependency in ("source-verification", "build-binary", "package-vsix", "build-wheel"):
        if dependency not in preflight:
            raise ValueError(f"preflight must depend on {dependency}")
    for publish_job in ("publish-pypi", "publish"):
        block = _job_block(workflow, publish_job)
        if not re.search(r"(?m)^\s{4}needs:\s*preflight\s*$", block):
            raise ValueError(f"{publish_job} must depend only on preflight")


def _artifact_map(artifacts_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(item for item in artifacts_dir.rglob("*") if item.is_file()):
        if path.name in result:
            raise ValueError(f"duplicate artifact filename: {path.name}")
        result[path.name] = path
    return result


def _normalized_contract(contract: dict[str, Any], version: str) -> dict[str, Any]:
    normalized = dict(contract)
    normalized["version"] = version
    return normalized


def write_checksum_manifest(paths: list[Path], output_path: Path) -> None:
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in sorted(paths, key=lambda item: item.name)
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_artifacts(artifacts_dir: Path, version: str, output_dir: Path) -> list[Path]:
    artifacts = _artifact_map(artifacts_dir)
    expected_names = {
        f"onec-hbk-bsl-{target}" + (".exe" if target == "win32-x64" else "") for target in TARGETS
    }
    expected_names.update(f"onec-hbk-bsl-{version}-{target}.vsix" for target in TARGETS)
    for distribution in ("onec_hbk_bsl_core", "onec_hbk_bsl"):
        expected_names.add(f"{distribution}-{version}-py3-none-any.whl")
        expected_names.add(f"{distribution}-{version}.tar.gz")
    missing = sorted(expected_names - artifacts.keys())
    if missing:
        raise ValueError("missing release artifacts: " + ", ".join(missing))

    source = _normalized_contract(source_contract(), version)
    contract_names = {f"contract-{target}.json" for target in TARGETS}
    contract_names.add("contract-wheel.json")
    for name in sorted(contract_names):
        path = artifacts.get(name)
        if path is None:
            raise ValueError(f"missing executed artifact contract: {name}")
        contract = json.loads(path.read_text(encoding="utf-8"))
        if contract != source:
            raise ValueError(f"artifact contract mismatch: {name}")

    core_wheel = artifacts[f"onec_hbk_bsl_core-{version}-py3-none-any.whl"]
    with zipfile.ZipFile(core_wheel) as archive:
        api_json = [
            name
            for name in archive.namelist()
            if "/data/platform_api/" in name and name.endswith(".json")
        ]
        if len(api_json) < 50:
            raise ValueError("core wheel does not contain the platform API resources")

    for target in TARGETS:
        name = f"onec-hbk-bsl-{version}-{target}.vsix"
        with zipfile.ZipFile(artifacts[name]) as archive:
            manifest = json.loads(archive.read("extension/package.json"))
            if manifest.get("version") != version:
                raise ValueError(f"{name} manifest version mismatch")
            required = {"extension/out/extension.js"}
            binary = (
                "extension/bin/onec-hbk-bsl.exe"
                if target == "win32-x64"
                else "extension/bin/onec-hbk-bsl"
            )
            required.add(binary)
            absent = required - set(archive.namelist())
            if absent:
                raise ValueError(f"{name} is missing: {', '.join(sorted(absent))}")

    output_dir.mkdir(parents=True, exist_ok=True)
    release_assets: list[Path] = []
    for name in sorted(expected_names):
        destination = output_dir / name
        destination.write_bytes(artifacts[name].read_bytes())
        release_assets.append(destination)
    checksum_path = output_dir / "SHA256SUMS"
    write_checksum_manifest(release_assets, checksum_path)
    return [*release_assets, checksum_path]


def verify_changelog(
    version: str,
    *,
    allow_unreleased: bool = False,
    changelog_path: Path | None = None,
) -> None:
    path = changelog_path or ROOT / "CHANGELOG.md"
    changelog = path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog):
        return
    if allow_unreleased:
        section = re.search(
            r"(?ms)^## \[Unreleased\]\s*\n(?P<body>.*?)(?=^## \[|\Z)",
            changelog,
        )
        if section is not None and re.search(r"(?m)^- \S", section.group("body")):
            return
        raise ValueError("CHANGELOG.md has no non-empty Unreleased section")
    raise ValueError(f"CHANGELOG.md has no dated {version} section")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    source_parser = subparsers.add_parser("source")
    source_parser.add_argument("--coverage-json", type=Path, required=True)
    source_parser.add_argument("--base", default="origin/main")
    source_parser.add_argument("--version")
    artifact_parser = subparsers.add_parser("artifacts")
    artifact_parser.add_argument("--artifacts-dir", type=Path, required=True)
    artifact_parser.add_argument("--output-dir", type=Path, required=True)
    artifact_parser.add_argument("--version", required=True)
    artifact_parser.add_argument("--allow-unreleased-changelog", action="store_true")
    args = parser.parse_args()

    if args.command == "source":
        source_contract()
        verify_generated_docs()
        verify_release_dag()
        verify_coverage(
            args.coverage_json,
            changed_lines=changed_python_lines(args.base),
        )
        if args.version:
            verify_changelog(args.version)
        return 0

    verify_changelog(args.version, allow_unreleased=args.allow_unreleased_changelog)
    verify_release_dag()
    verify_artifacts(args.artifacts_dir, args.version, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
