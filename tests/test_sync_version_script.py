from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _load_sync_version_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "sync_version.py"
    spec = importlib.util.spec_from_file_location("sync_version_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_only_updates_python_version_without_touching_extension(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_sync_version_module()

    ext = tmp_path / "vscode-extension"
    ext.mkdir()
    package_json = ext / "package.json"
    package_json.write_text(json.dumps({"version": "0.1.0"}) + "\n", encoding="utf-8")

    py_version = tmp_path / "src" / "onec_hbk_bsl" / "_version.py"
    py_version.parent.mkdir(parents=True)
    py_version.write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    run = MagicMock()
    monkeypatch.setattr(module, "EXT", ext)
    monkeypatch.setattr(module, "PY_VERSION", py_version)
    monkeypatch.setattr(module, "_release_version", lambda: "1.2.3")
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["sync_version.py", "--runtime-only"])

    assert module.main() == 0

    assert '__version__ = "1.2.3"' in py_version.read_text(encoding="utf-8")
    assert json.loads(package_json.read_text(encoding="utf-8"))["version"] == "0.1.0"
    run.assert_not_called()


def test_release_version_prefers_explicit_release_env(monkeypatch) -> None:
    module = _load_sync_version_module()

    monkeypatch.setenv("SETUPTOOLS_SCM_PRETEND_VERSION", "v2.3.4")
    monkeypatch.setenv("GITHUB_REF_NAME", "v1.2.3")
    monkeypatch.setattr(module, "_version_from_latest_tag", lambda: "0.0.1")

    assert module._release_version() == "2.3.4"


def test_release_version_uses_tag_ref_before_git_describe(monkeypatch) -> None:
    module = _load_sync_version_module()

    monkeypatch.delenv("SETUPTOOLS_SCM_PRETEND_VERSION", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v3.4.5")
    monkeypatch.setattr(module, "_version_from_latest_tag", lambda: "0.0.1")

    assert module._release_version() == "3.4.5"


def test_release_version_ignores_non_tag_branch_ref(monkeypatch) -> None:
    module = _load_sync_version_module()

    monkeypatch.delenv("SETUPTOOLS_SCM_PRETEND_VERSION", raising=False)
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setattr(module, "_version_from_latest_tag", lambda: "4.5.6")

    assert module._release_version() == "4.5.6"
