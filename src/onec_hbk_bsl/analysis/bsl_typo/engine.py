from __future__ import annotations

import importlib.resources
import re
import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from onec_hbk_bsl.analysis.bsl_typo.candidates import collect_spell_candidates
from onec_hbk_bsl.analysis.bsl_typo.lexicon import DOMAIN_TOKEN_IGNORE, KNOWN_TYPO_TOKENS
from onec_hbk_bsl.analysis.bsl_typo.models import BslTypoConfig, SpellCandidate, SpellIssue
from onec_hbk_bsl.analysis.bsl_typo.tokenization import (
    fragment_needs_ru_typo_scan,
    split_by_character_type_camel_case,
)

SpellFn = Callable[[str], bool]

_init_lock = threading.Lock()
_spell_ru: Any | None = None
_morph_ru: Any | None = None


def _load_bslls_typo_properties_text() -> str:
    ref = importlib.resources.files("onec_hbk_bsl.analysis.bsl_typo") / (
        "TypoDiagnostic_ru.properties"
    )
    with ref.open(encoding="utf-8") as f:
        return f.read()


def _parse_bslls_properties(raw: str) -> dict[str, str]:
    buf: list[str] = []
    merged: list[str] = []
    for line in raw.splitlines():
        s = line.rstrip()
        if s.endswith("\\"):
            buf.append(s[:-1].rstrip())
        else:
            buf.append(s)
            merged.append("".join(buf).strip())
            buf = []
    props: dict[str, str] = {}
    for line in merged:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            props[key.strip()] = value.strip()
    return props


@lru_cache(maxsize=1)
def load_typo_config_ru() -> BslTypoConfig:
    props = _parse_bslls_properties(_load_bslls_typo_properties_text())
    exceptions_raw = props.get("diagnosticExceptions", "")
    collapsed = re.sub(r"\s+", "", exceptions_raw)
    ignore_set = frozenset(w.casefold() for w in collapsed.split(",") if w)
    return BslTypoConfig(
        message_fmt=props.get("diagnosticMessage", 'Возможная опечатка в "%s"'),
        language_short=props.get("diagnosticLanguage", "ru").strip().lower(),
        words_to_ignore=ignore_set,
    )


def _get_spell_ru() -> Any:
    global _spell_ru
    with _init_lock:
        if _spell_ru is None:
            from spellchecker import SpellChecker

            _spell_ru = SpellChecker(language="ru")
    return _spell_ru


def _get_morph_ru() -> Any:
    global _morph_ru
    with _init_lock:
        if _morph_ru is None:
            from pymorphy3 import MorphAnalyzer

            _morph_ru = MorphAnalyzer(lang="ru")
    return _morph_ru


@lru_cache(maxsize=100_000)
def default_spell_fn(word: str) -> bool:
    if not fragment_needs_ru_typo_scan(word):
        return False
    normalized = word.casefold()
    spell = _get_spell_ru()
    if normalized in spell:
        return False
    morph = _get_morph_ru()
    return not any(parse.is_known for parse in morph.parse(word))


def reset_typo_engine_for_tests() -> None:
    global _spell_ru, _morph_ru
    with _init_lock:
        _spell_ru = None
        _morph_ru = None
    load_typo_config_ru.cache_clear()
    default_spell_fn.cache_clear()
    split_by_character_type_camel_case.cache_clear()


def language_tool_available() -> bool:
    return False


def spellcheck_typo_diagnostics(
    *,
    path: str,
    tree: Any,
    cfg: BslTypoConfig | None = None,
    spell_fn: SpellFn | None = None,
) -> list[dict[str, Any]]:
    cfg = cfg or load_typo_config_ru()
    issues = check_tree_for_typos(tree=tree, cfg=cfg, spell_fn=spell_fn)
    return spellcheck_candidate_diagnostics(path=path, issues=issues, cfg=cfg)


def spellcheck_candidate_diagnostics(
    *,
    path: str,
    candidates: list[SpellCandidate] | None = None,
    issues: list[SpellIssue] | None = None,
    cfg: BslTypoConfig | None = None,
    spell_fn: SpellFn | None = None,
) -> list[dict[str, Any]]:
    cfg = cfg or load_typo_config_ru()
    if issues is None:
        if candidates is None:
            candidates = []
        issues = check_candidates_for_typos(candidates=candidates, cfg=cfg, spell_fn=spell_fn)
    return [
        {
            "file": path,
            "line": issue.candidate.line,
            "character": issue.candidate.character,
            "end_line": issue.candidate.end_line,
            "end_character": issue.candidate.end_character,
            "code": "BSL256",
            "message": cfg.message_fmt % issue.word,
        }
        for issue in issues
    ]


def check_tree_for_typos(
    *,
    tree: Any,
    cfg: BslTypoConfig,
    spell_fn: SpellFn | None = None,
) -> list[SpellIssue]:
    candidates = collect_spell_candidates(tree=tree)
    return check_candidates_for_typos(candidates=candidates, cfg=cfg, spell_fn=spell_fn)


def check_candidates_for_typos(
    *,
    candidates: list[SpellCandidate],
    cfg: BslTypoConfig,
    spell_fn: SpellFn | None = None,
) -> list[SpellIssue]:
    candidate_parts = list(_iter_candidate_parts(candidates, cfg))
    words_to_check = {
        normalized: part
        for _, part, normalized, forced in candidate_parts
        if not forced and fragment_needs_ru_typo_scan(part)
    }
    checker = spell_fn or default_spell_fn
    checked = {
        normalized: checker(original) for normalized, original in sorted(words_to_check.items())
    }

    issues: list[SpellIssue] = []
    seen_candidates: set[SpellCandidate] = set()
    for candidate, part, normalized, forced in candidate_parts:
        if forced or checked.get(normalized, False):
            if candidate in seen_candidates:
                continue
            seen_candidates.add(candidate)
            issues.append(SpellIssue(word=part, candidate=candidate))
            continue
    return issues


def _iter_candidate_parts(
    candidates: list[SpellCandidate],
    cfg: BslTypoConfig,
) -> list[tuple[SpellCandidate, str, str, bool]]:
    result: list[tuple[SpellCandidate, str, str, bool]] = []
    for candidate in candidates:
        candidate_normalized = candidate.text.casefold()
        if (
            candidate_normalized in cfg.words_to_ignore
            and candidate_normalized not in KNOWN_TYPO_TOKENS
        ):
            continue
        for part in split_by_character_type_camel_case(candidate.text):
            normalized = part.casefold()
            forced = normalized in KNOWN_TYPO_TOKENS
            if candidate.kind == "method" and not forced:
                continue
            if (
                forced
                and candidate.kind == "string"
                and normalized == "субконто"
                and "\n" in candidate.text
            ):
                continue
            if not forced and normalized in cfg.words_to_ignore:
                continue
            if not forced and normalized in candidate.exact_ignore:
                continue
            if not forced and normalized in DOMAIN_TOKEN_IGNORE:
                continue
            if len(part) < cfg.min_word_length:
                continue
            if not forced and not fragment_needs_ru_typo_scan(part):
                continue
            result.append((candidate, part, normalized, forced))
    return result
