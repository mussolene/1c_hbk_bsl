"""Internal BSL-aware typo engine.

This package intentionally contains the product implementation, not adapters to
external spell-check services.  The public diagnostics layer maps issues from
this package to BSLLS-compatible ``BSL256`` diagnostics.
"""

from onec_hbk_bsl.analysis.bsl_typo.engine import (
    BslTypoConfig,
    SpellFn,
    default_spell_fn,
    language_tool_available,
    load_typo_config_ru,
    reset_typo_engine_for_tests,
    spellcheck_typo_diagnostics,
)
from onec_hbk_bsl.analysis.bsl_typo.tokenization import (
    contains_cyrillic_letter,
    contains_latin_letter,
    split_by_character_type_camel_case,
)

__all__ = [
    "BslTypoConfig",
    "SpellFn",
    "contains_cyrillic_letter",
    "contains_latin_letter",
    "default_spell_fn",
    "language_tool_available",
    "load_typo_config_ru",
    "reset_typo_engine_for_tests",
    "spellcheck_typo_diagnostics",
    "split_by_character_type_camel_case",
]
