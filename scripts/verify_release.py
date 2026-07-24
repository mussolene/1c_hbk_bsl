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
from email.parser import Parser
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("darwin-arm64", "darwin-x64", "linux-x64", "win32-x64")
REQUIRED_PUBLIC_DOCS = {
    "diagnostic-rules.md",
    "extension.md",
    "index.md",
    "public-surface.md",
}
REQUIRED_CHANGELOG_HISTORY = {"0.8.41", "0.8.42"}
EXPECTED_PROJECT_URLS = {
    "Changelog": "https://github.com/mussolene/1c_hbk_bsl/blob/main/CHANGELOG.md",
    "Documentation": "https://mussolene.github.io/1c_hbk_bsl/",
    "Homepage": "https://github.com/mussolene/1c_hbk_bsl",
    "Issues": "https://github.com/mussolene/1c_hbk_bsl/issues",
    "Repository": "https://github.com/mussolene/1c_hbk_bsl",
}
EXPECTED_KEYWORDS = {"1c", "bsl", "formatter", "linter", "lsp", "mcp", "vscode"}
REQUIRED_CLASSIFIERS = {
    "Development Status :: 4 - Beta",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
}


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
    expected_pages = module.expected_rule_pages()
    actual_paths = set((ROOT / "docs" / "rule-contracts").glob("BSL*.md"))
    if actual_paths != set(expected_pages):
        missing = sorted(str(path.relative_to(ROOT)) for path in set(expected_pages) - actual_paths)
        extra = sorted(str(path.relative_to(ROOT)) for path in actual_paths - set(expected_pages))
        raise ValueError(f"rule documentation coverage mismatch: missing={missing}, extra={extra}")
    stale = [
        str(path.relative_to(ROOT))
        for path, content in expected_pages.items()
        if path.read_text(encoding="utf-8") != content
    ]
    if stale:
        raise ValueError("stale generated rule page headers: " + ", ".join(stale))
    incomplete = [
        str(path.relative_to(ROOT))
        for path in expected_pages
        if "<!-- localized-rule-description:start -->" not in path.read_text(encoding="utf-8")
    ]
    if incomplete:
        raise ValueError("rule pages without localized descriptions: " + ", ".join(incomplete))
    internal = [
        str(path.relative_to(ROOT))
        for path in expected_pages
        if "<!-- engineering-contract:start -->" in path.read_text(encoding="utf-8")
    ]
    if internal:
        raise ValueError("public rule pages contain engineering contracts: " + ", ".join(internal))


def verify_published_docs_independence(root: Path = ROOT) -> None:
    forbidden_link = re.compile(
        r"\]\(https?://(?:www\.)?github\.com/1c-syntax/bsl-language-server(?:[)/#?]|$)",
        re.IGNORECASE,
    )
    failures: list[str] = []
    for path in sorted((root / "docs").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if forbidden_link.search(text):
            failures.append(str(path.relative_to(root)))
    if failures:
        raise ValueError(
            "published documentation links to an adjacent analyzer repository: "
            + ", ".join(failures)
        )


def _markdown_files(root: Path) -> list[Path]:
    candidates = [
        root / "README.md",
        root / "CONTRIBUTING.md",
        root / "CHANGELOG.md",
        root / "SECURITY.md",
        root / "vscode-extension" / "README.md",
        *(root / ".github").rglob("*.md"),
        *(root / "docs").rglob("*.md"),
    ]
    return sorted({path for path in candidates if path.is_file()})


def _heading_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match is None:
            continue
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", match.group(1))
        text = re.sub(r"[`*_~]", "", text).strip().lower()
        slug = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
        slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
        duplicate = counts.get(slug, 0)
        counts[slug] = duplicate + 1
        anchors.add(slug if duplicate == 0 else f"{slug}-{duplicate}")
    return anchors


def verify_local_markdown_links(root: Path = ROOT) -> None:
    failures: list[str] = []
    for source in _markdown_files(root):
        text = source.read_text(encoding="utf-8")
        links = re.findall(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)", text)
        links.extend(match.group(1) for match in re.finditer(r"(?m)^\[[^\]]+\]:\s*(\S+)\s*$", text))
        for raw_link in links:
            if raw_link.startswith(("http://", "https://", "mailto:")):
                continue
            target_text, _, fragment = raw_link.partition("#")
            target = source if not target_text else source.parent / unquote(target_text)
            try:
                target = target.resolve()
                target.relative_to(root.resolve())
            except ValueError:
                failures.append(f"{source.relative_to(root)}: path escapes repository: {raw_link}")
                continue
            if not target.exists():
                failures.append(f"{source.relative_to(root)}: missing {raw_link}")
                continue
            if fragment and target.suffix.lower() == ".md":
                anchor = unquote(fragment).lower()
                if anchor not in _heading_anchors(target):
                    failures.append(f"{source.relative_to(root)}: missing anchor {raw_link}")
    if failures:
        raise ValueError("broken local documentation links:\n" + "\n".join(failures))


def verify_public_documentation(root: Path = ROOT) -> None:
    docs = root / "docs"
    missing = sorted(name for name in REQUIRED_PUBLIC_DOCS if not (docs / name).is_file())
    if missing:
        raise ValueError("public documentation is missing: " + ", ".join(missing))

    unlocalized: list[str] = []
    for name in sorted(REQUIRED_PUBLIC_DOCS):
        text = (docs / name).read_text(encoding="utf-8")
        if "doc-lang-ru" not in text or "doc-lang-en" not in text:
            unlocalized.append(name)
    if unlocalized:
        raise ValueError("public documentation is not bilingual: " + ", ".join(unlocalized))

    package = json.loads((root / "vscode-extension" / "package.json").read_text(encoding="utf-8"))
    extension = (docs / "extension.md").read_text(encoding="utf-8")
    settings = package["contributes"]["configuration"]["properties"]
    undocumented = sorted(key for key in settings if f"`{key}`" not in extension)
    if undocumented:
        raise ValueError("extension settings are undocumented: " + ", ".join(undocumented))


def _project_public_metadata(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        project = tomllib.load(stream)["project"]
    return {
        "urls": project.get("urls"),
        "keywords": set(project.get("keywords", ())),
        "classifiers": set(project.get("classifiers", ())),
    }


def verify_package_metadata(root: Path = ROOT) -> None:
    paths = (root / "pyproject.toml", root / "packages" / "onec-hbk-bsl" / "pyproject.toml")
    metadata = [_project_public_metadata(path) for path in paths]
    if metadata[0] != metadata[1]:
        raise ValueError("core and meta package public metadata differ")
    public = metadata[0]
    if public["urls"] != EXPECTED_PROJECT_URLS:
        raise ValueError("package project URLs do not match the public repository contract")
    if public["keywords"] != EXPECTED_KEYWORDS:
        raise ValueError("package keywords do not match the public repository contract")
    missing = sorted(REQUIRED_CLASSIFIERS - public["classifiers"])
    if missing:
        raise ValueError("package classifiers are missing: " + ", ".join(missing))


def verify_community_files(root: Path = ROOT) -> None:
    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    required_security = (
        "Latest published release",
        "security/advisories/new",
        "Do not open a public issue",
    )
    missing_security = [value for value in required_security if value not in security]
    if missing_security:
        raise ValueError("SECURITY.md is missing: " + ", ".join(missing_security))
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", security):
        raise ValueError("SECURITY.md must not require a personal email address")

    bug = root / ".github" / "ISSUE_TEMPLATE" / "bug_report.md"
    text = bug.read_text(encoding="utf-8")
    frontmatter = re.match(r"(?s)^---\n(?P<body>.*?)\n---\n", text)
    if frontmatter is None:
        raise ValueError("bug report template has invalid frontmatter")
    fields = {
        match.group(1): match.group(2).strip().strip('"')
        for match in re.finditer(r"(?m)^([a-z_]+):\s*(.*)$", frontmatter.group("body"))
    }
    if set(fields) != {"about", "assignees", "labels", "name", "title"}:
        raise ValueError("bug report frontmatter fields are incomplete")
    required_bug_sections = ("## Version And Platform", "## Reproducer", "## Verification")
    if any(section not in text for section in required_bug_sections):
        raise ValueError("bug report template is missing required reproduction fields")

    pull_request = (root / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    required_pr_sections = (
        "## Scope",
        "## Version, Platform And Reproducer",
        "## Verification",
        "## Risk And Compatibility",
    )
    if any(section not in pull_request for section in required_pr_sections):
        raise ValueError("pull request template is missing required verification fields")


def verify_changelog_integrity(changelog_path: Path | None = None) -> None:
    path = changelog_path or ROOT / "CHANGELOG.md"
    changelog = path.read_text(encoding="utf-8")
    versions = re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", changelog)
    duplicates = sorted({version for version in versions if versions.count(version) > 1})
    if duplicates:
        raise ValueError("duplicate changelog versions: " + ", ".join(duplicates))
    missing = sorted(REQUIRED_CHANGELOG_HISTORY - set(versions))
    if missing:
        raise ValueError("CHANGELOG.md is missing historical releases: " + ", ".join(missing))
    if not versions:
        raise ValueError("CHANGELOG.md has no dated releases")
    unreleased = re.search(
        r"(?m)^\[Unreleased\]:\s+\S+/compare/v(?P<base>\d+\.\d+\.\d+)\.\.\.HEAD$",
        changelog,
    )
    if unreleased is None or unreleased.group("base") != versions[0]:
        raise ValueError("Unreleased comparison must start at the latest dated release")
    missing_refs = [
        version
        for version in REQUIRED_CHANGELOG_HISTORY | {versions[0]}
        if not re.search(rf"(?m)^\[{re.escape(version)}\]:\s+\S+$", changelog)
    ]
    if missing_refs:
        raise ValueError(
            "CHANGELOG.md is missing comparison links: " + ", ".join(sorted(missing_refs))
        )


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


def _wheel_public_metadata(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        message = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
    urls = dict(
        value.split(", ", 1) for value in message.get_all("Project-URL", ()) if ", " in value
    )
    keywords = {
        keyword.strip()
        for value in message.get_all("Keywords", ())
        for keyword in value.split(",")
        if keyword.strip()
    }
    return {
        "urls": urls,
        "keywords": keywords,
        "classifiers": set(message.get_all("Classifier", ())),
    }


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
    meta_wheel = artifacts[f"onec_hbk_bsl-{version}-py3-none-any.whl"]
    wheel_metadata = [_wheel_public_metadata(path) for path in (core_wheel, meta_wheel)]
    if wheel_metadata[0] != wheel_metadata[1]:
        raise ValueError("core and meta wheel public metadata differ")
    if wheel_metadata[0]["urls"] != EXPECTED_PROJECT_URLS:
        raise ValueError("wheel project URLs do not match the public repository contract")
    if wheel_metadata[0]["keywords"] != EXPECTED_KEYWORDS:
        raise ValueError("wheel keywords do not match the public repository contract")
    missing_classifiers = sorted(REQUIRED_CLASSIFIERS - wheel_metadata[0]["classifiers"])
    if missing_classifiers:
        raise ValueError("wheel classifiers are missing: " + ", ".join(missing_classifiers))
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
        verify_published_docs_independence()
        verify_local_markdown_links()
        verify_public_documentation()
        verify_package_metadata()
        verify_community_files()
        verify_changelog_integrity()
        verify_release_dag()
        verify_coverage(
            args.coverage_json,
            changed_lines=changed_python_lines(args.base),
        )
        if args.version:
            verify_changelog(args.version)
        return 0

    verify_changelog(args.version, allow_unreleased=args.allow_unreleased_changelog)
    verify_changelog_integrity()
    verify_release_dag()
    verify_artifacts(args.artifacts_dir, args.version, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
