"""Backward-compatible facade for the internal BSL typo engine.

New code should use :mod:`onec_hbk_bsl.analysis.bsl_typo`.  This module keeps
the historical import path and test monkeypatch points used by diagnostics.
"""

from __future__ import annotations

from typing import Any

from onec_hbk_bsl.analysis.bsl_typo import (
    BslTypoConfig as BsllsTypoConfig,
)
from onec_hbk_bsl.analysis.bsl_typo import (
    SpellFn,
    contains_cyrillic_letter,
    contains_latin_letter,
    default_spell_fn,
    language_tool_available,
    load_typo_config_ru,
    reset_typo_engine_for_tests,
    split_by_character_type_camel_case,
)
from onec_hbk_bsl.analysis.bsl_typo.engine import spellcheck_typo_diagnostics as _spellcheck


def spellcheck_typo_diagnostics(
    *,
    path: str,
    tree: Any,
    cfg: BsllsTypoConfig | None = None,
    spell_fn: SpellFn | None = None,
) -> list[dict[str, Any]]:
    return _spellcheck(
        path=path,
        tree=tree,
        cfg=cfg,
        spell_fn=spell_fn or default_spell_fn,
    )


reset_language_tool_for_tests = reset_typo_engine_for_tests

__all__ = [
    "BsllsTypoConfig",
    "SpellFn",
    "contains_cyrillic_letter",
    "contains_latin_letter",
    "default_spell_fn",
    "language_tool_available",
    "load_typo_config_ru",
    "reset_language_tool_for_tests",
    "reset_typo_engine_for_tests",
    "spellcheck_typo_diagnostics",
    "split_by_character_type_camel_case",
]
