"""Version string matches setuptools-scm (git tags)."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def test_version_matches_setuptools_scm() -> None:
    from setuptools_scm import get_version

    expected = get_version(root=str(_REPO))
    from onec_hbk_bsl import __version__

    assert __version__ == expected
