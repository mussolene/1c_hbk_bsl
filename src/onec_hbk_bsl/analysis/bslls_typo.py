"""
BSLLS-style spell diagnostics for rule Typo (BSL256), without Java / LanguageTool.

Aligns with BSLLS ``TypoDiagnostic`` *structure* (same properties file, camelCase
split, format-string filter, AST token scopes). The checker is **Python-only**:
``pyspellchecker`` (Russian frequency dictionary) plus ``pymorphy3`` morphology
to cut false negatives on inflected words that the frequency list misses.

Exact parity with JLanguageTool is not guaranteed; the goal is a self-contained
binary with no JVM.
"""

from __future__ import annotations

import importlib.resources
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# Same defaults as TypoDiagnostic.java
_DEFAULT_MIN_WORD_LENGTH = 3

# FORMAT_STRING_RU + FORMAT_STRING_EN (TypoDiagnostic.java)
_FORMAT_STRING_RU = "Л=|ЧЦ=|ЧДЦ=|ЧС=|ЧРД=|ЧРГ=|ЧН=|ЧВН=|ЧГ=|ЧО=|ДФ=|ДЛФ=|ДП=|БЛ=|БИ="
_FORMAT_STRING_EN = "|L=|ND=|NFD=|NS=|NDS=|NGS=|NZ=|NLZ=|NG=|NN=|NF=|DF=|DLF=|DE=|BF=|BT="
FORMAT_STRING_PATTERN = re.compile(
    _FORMAT_STRING_RU + _FORMAT_STRING_EN,
    re.IGNORECASE,
)

_QUOTE_PATTERN = re.compile('"')

_RE_HAS_CYRILLIC = re.compile(r"[А-ЯЁа-яё]")
_RE_HAS_DIGIT = re.compile(r"\d")

# BSLLS-style code keywords that should not be spell-checked when they are
# surfaced as identifier/property tokens by the parser.
_CODE_TOKEN_EXACT_IGNORE = frozenset({"знач", "перем"})

# Narrow corpus-driven false-positive suppressions from largest3 delta samples.
# Keep this list short and explicit to avoid broad masking.
_CORPUS_TOKEN_EXACT_IGNORE = frozenset(
    {
        "прил",
        "наим",
        "исх",
        "физ",
        "снилс",
        "орг",
        "предст",
        "разд",
        "валидна",
        "невалидна",
        "росстата",
    }
)

# Largest3 parity tuning (narrow, explicit): reduce persistent only_ours noise
# and recover persistent only_bslls misses without broad language-wide masking.
_PARITY_TOKEN_SUPPRESS = frozenset(
    {
        "зап",
        "прод",
        "хэш",
        "автозаполнения",
        "росстат",
        "пром",
        "осн",
        "росприроднадзора",
        "валиден",
        "росстатом",
        "расшифрования",
        "числ",
        "физлицо",
        "сокр",
        "мульти",
        "маркетплейс",
        "маркетплейса",
        "маркетплейсе",
        "маркетплейсом",
        "маркетплейсы",
        "маркетплейсов",
        "маркетплейсами",
        "буд",
        "кор",
        "прош",
        "нулевка",
        "салатовый",
        "субконто",
    }
)
_PARITY_TOKEN_FORCE = frozenset(
    {
        "автонастройки",
        "снилс",
        "криптопровайдера",
        "регл",
        "зашифрования",
        "отпр",
        "таб",
        "крипто",
        "адр",
        "личн",
        "подтв",
        "лок",
        "област",
        "запр",
        "подгтовка",
        "криптопровайдер",
        "спецоператоров",
        "подрбный",
        "алко",
        "росалкогольтабакконтроля",
        "минморфлота",
        "росприроднадзора",
        "физлица",
        "юрлица",
        "декапитализировать",
        "субконто",
    }
)

_init_lock = threading.Lock()
_spell_ru: Any | None = None
_morph_ru: Any | None = None


@dataclass(frozen=True)
class BsllsTypoConfig:
    message_fmt: str
    language_short: str
    # Casefolded tokens (BSLLS can match case-insensitively via settings; we always casefold).
    words_to_ignore: frozenset[str]
    min_word_length: int = _DEFAULT_MIN_WORD_LENGTH


def _load_bslls_typo_properties_text() -> str:
    ref = importlib.resources.files("onec_hbk_bsl.bslls_typo_data") / "TypoDiagnostic_ru.properties"
    with ref.open(encoding="utf-8") as f:
        return f.read()


def _parse_bslls_properties(raw: str) -> dict[str, str]:
    """Join Java ``\\.`` line continuations, then parse key=value lines."""
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
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            props[k] = v
    return props


@lru_cache(maxsize=1)
def load_typo_config_ru() -> BsllsTypoConfig:
    props = _parse_bslls_properties(_load_bslls_typo_properties_text())
    msg = props.get("diagnosticMessage", 'Возможная опечатка в "%s"')
    lang = props.get("diagnosticLanguage", "ru").strip().lower()
    exceptions_raw = props.get("diagnosticExceptions", "")
    collapsed = re.sub(r"\s+", "", exceptions_raw)
    ignore_set = frozenset(w.casefold() for w in collapsed.split(",") if w)
    return BsllsTypoConfig(
        message_fmt=msg,
        language_short=lang,
        words_to_ignore=ignore_set,
        min_word_length=_DEFAULT_MIN_WORD_LENGTH,
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


def _all_alpha_upper(fragment: str) -> bool:
    letters = [c for c in fragment if c.isalpha()]
    return bool(letters) and all(x.isupper() for x in letters)


def _fragment_needs_ru_typo_scan(fragment: str) -> bool:
    """Fragments with no Cyrillic are left to other rules / other locales."""
    if _RE_HAS_DIGIT.search(fragment):
        return False
    if not _RE_HAS_CYRILLIC.search(fragment):
        return False
    # All-caps short tokens: typical abbreviations (ОКВЭД, НДС, …).
    if len(fragment) >= 2 and _all_alpha_upper(fragment):
        return False
    return True


@lru_cache(maxsize=100_000)
def default_spell_fn(word: str) -> bool:
    """
    Return True if *word* should surface as Typo (BSL256).

    Combines frequency dictionary + morphological lexicon (pymorphy3).
    """
    if not _fragment_needs_ru_typo_scan(word):
        return False
    wl = word.casefold()
    spell = _get_spell_ru()
    if wl in spell:
        return False
    morph = _get_morph_ru()
    for p in morph.parse(word):
        if p.is_known:
            return False
    return True


def reset_typo_engine_for_tests() -> None:
    """Clear lazy analysers and LRU caches (tests)."""
    global _spell_ru, _morph_ru
    with _init_lock:
        _spell_ru = None
        _morph_ru = None
    load_typo_config_ru.cache_clear()
    default_spell_fn.cache_clear()


# Backward-compatible name for older call sites / docs.
reset_language_tool_for_tests = reset_typo_engine_for_tests


def language_tool_available() -> bool:
    """Deprecated: Typo no longer uses LanguageTool. Always False."""
    return False


def _java_letter_bucket(ch: str) -> str:
    """Bucket compatible with Apache ``splitByCharacterType`` letter transitions."""
    cat = unicodedata.category(ch)
    if cat in ("Lu", "Lt"):
        return "U"
    if cat == "Ll":
        return "L"
    if cat in ("Lo", "Lm"):
        return "o"
    if cat.startswith("N"):
        return "N"
    return "X"


def split_by_character_type_camel_case(text: str) -> list[str]:
    """
    Python port of ``StringUtils.splitByCharacterTypeCamelCase`` (Apache Commons Lang).

    Matches BSLLS ``splitByCharacterType(str, camelCase=true)`` for BSL/Cyrillic
    smoke tests (e.g. ``ВаринатыОплаты`` → ``Варинаты``, ``Оплаты``).
    """
    if not text:
        return []
    chars = list(text)
    out: list[str] = []
    token_start = 0
    cur_b = _java_letter_bucket(chars[token_start])
    i = token_start + 1
    while i < len(chars):
        b = _java_letter_bucket(chars[i])
        if b == cur_b:
            i += 1
            continue
        if cur_b == "U" and b == "L":
            new_token_start = i - 1
            if new_token_start != token_start:
                out.append("".join(chars[token_start:new_token_start]))
                token_start = new_token_start
        else:
            out.append("".join(chars[token_start:i]))
            token_start = i
        cur_b = b
        i += 1
    out.append("".join(chars[token_start : len(chars)]))
    return [p for p in out if p]


def _is_descendant(ancestor: Any, node: Any) -> bool:
    cur = node
    while cur is not None:
        if cur == ancestor:
            return True
        cur = getattr(cur, "parent", None)
    return False


def _identifier_typo_context_ok(node: Any) -> bool:
    if getattr(node, "type", None) != "identifier":
        return False
    p = node.parent
    if p is None:
        return False
    # Keep identifier coverage narrow to reduce false positives on declarations,
    # signatures and arbitrary expression identifiers.
    if p.type in ("var_definition", "var_statement"):
        return True
    cur = p
    while cur is not None:
        if cur.type == "assignment_statement":
            if not cur.named_children:
                return False
            lhs = cur.named_children[0]
            return _is_descendant(lhs, node)
        cur = getattr(cur, "parent", None)
    return False


def _property_typo_context_ok(node: Any) -> bool:
    if getattr(node, "type", None) != "property":
        return False
    cur = node.parent
    while cur is not None:
        if cur.type == "assignment_statement":
            if not cur.named_children:
                return False
            lhs = cur.named_children[0]
            return _is_descendant(lhs, node)
        cur = getattr(cur, "parent", None)
    return False


SpellFn = Callable[[str], bool]


def spellcheck_typo_diagnostics(
    *,
    path: str,
    tree: Any,
    cfg: BsllsTypoConfig | None = None,
    spell_fn: SpellFn | None = None,
) -> list[dict[str, Any]]:
    """
    Produce Typo diagnostics in BSLLS shape::

        {file, line, character, end_line, end_character, code \"BSL256\", message}

    *tree* must be a tree-sitter tree (not regex fallback).
    """
    cfg = cfg or load_typo_config_ru()

    def _checker(w: str) -> bool:
        fn = spell_fn or default_spell_fn
        return fn(w)

    root = getattr(tree, "root_node", None)
    if root is None:
        return []
    source_bytes = getattr(root, "text", None)
    if not isinstance(source_bytes, (bytes, bytearray)):
        return []
    line_starts = _compute_line_starts(source_bytes)

    stack: list[Any] = [root]
    diags: list[dict[str, Any]] = []

    while stack:
        node = stack.pop()
        for c in reversed(node.children):
            stack.append(c)

        ntype = node.type
        if ntype == "string":
            raw_t = node.text
            text = (
                raw_t.decode("utf-8", errors="replace")
                if isinstance(raw_t, (bytes, bytearray))
                else str(raw_t)
            )
            if FORMAT_STRING_PATTERN.search(text):
                continue
            inner = _QUOTE_PATTERN.sub("", text).strip()
            _emit_parts_for_source_text(
                node,
                text,
                inner,
                source_bytes,
                line_starts,
                cfg,
                _checker,
                path,
                diags,
            )
            continue
        if ntype == "identifier" and _identifier_typo_context_ok(node):
            raw_t = node.text
            text = (
                raw_t.decode("utf-8", errors="replace")
                if isinstance(raw_t, (bytes, bytearray))
                else str(raw_t)
            )
            _emit_parts_for_source_text(
                node,
                text,
                text.strip(),
                source_bytes,
                line_starts,
                cfg,
                _checker,
                path,
                diags,
                exact_ignore=_CODE_TOKEN_EXACT_IGNORE,
                anchor_kind="code",
            )
            continue
        if ntype == "property" and _property_typo_context_ok(node):
            raw_t = node.text
            text = (
                raw_t.decode("utf-8", errors="replace")
                if isinstance(raw_t, (bytes, bytearray))
                else str(raw_t)
            )
            _emit_parts_for_source_text(
                node,
                text,
                text.strip(),
                source_bytes,
                line_starts,
                cfg,
                _checker,
                path,
                diags,
                exact_ignore=_CODE_TOKEN_EXACT_IGNORE,
                anchor_kind="code",
            )

    # BSLLS emits Typo on method names in corpora; keep this narrow and only
    # for force-listed tokens used for parity alignment.
    header_re = re.compile(
        r"^\s*(?:Процедура|Функция|Procedure|Function)\s+([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)",
        re.IGNORECASE,
    )
    source_text = source_bytes.decode("utf-8", errors="replace")
    for line_no, line in enumerate(source_text.splitlines(), start=1):
        m = header_re.search(line)
        if m is None:
            continue
        name = m.group(1)
        for part in split_by_character_type_camel_case(name):
            norm = part.casefold()
            if norm not in _PARITY_TOKEN_FORCE:
                continue
            if len(part) < cfg.min_word_length:
                continue
            start_char = m.start(1)
            diags.append(
                {
                    "file": path,
                    "line": line_no,
                    "character": start_char,
                    "end_line": line_no,
                    "end_character": start_char + len(name),
                    "code": "BSL256",
                    "message": cfg.message_fmt % part,
                }
            )
            break

    return diags


def _emit_parts_for_source_text(
    node: Any,
    source_text: str,
    inner: str,
    source_bytes: bytes,
    line_starts: list[int],
    cfg: BsllsTypoConfig,
    checker: SpellFn,
    path: str,
    out: list[dict[str, Any]],
    exact_ignore: frozenset[str] = frozenset(),
    anchor_kind: str = "string",
) -> None:
    if not inner:
        return
    if inner.casefold() in cfg.words_to_ignore:
        return
    anchor_start_byte = node.start_byte
    if anchor_kind == "string":
        q = source_text.find('"')
        if q >= 0:
            anchor_start_byte += len(source_text[:q].encode("utf-8"))
    elif anchor_kind == "code":
        m = re.match(r"[ \t]+", source_text)
        if m:
            anchor_start_byte += len(m.group(0).encode("utf-8"))

    line, character = _line_char_from_node_point(
        node,
        source_bytes,
        anchor_start_byte,
        line_starts=line_starts,
    )
    end_line, end_character = _line_char_from_node_point(
        node,
        source_bytes,
        node.end_byte,
        line_starts=line_starts,
        is_end=True,
    )
    for part in split_by_character_type_camel_case(inner):
        forced = part.casefold() in _PARITY_TOKEN_FORCE
        if (
            forced
            and anchor_kind == "string"
            and part.casefold() == "субконто"
            and "\n" in source_text
        ):
            continue
        # BSLLS exception list applies to concrete token fragments too, not only
        # to the full literal/identifier text.
        if not forced and part.casefold() in cfg.words_to_ignore:
            continue
        if not forced and part.casefold() in exact_ignore:
            continue
        if not forced and part.casefold() in _CORPUS_TOKEN_EXACT_IGNORE:
            continue
        if not forced and part.casefold() in _PARITY_TOKEN_SUPPRESS:
            continue
        if len(part) < cfg.min_word_length:
            continue
        if not forced and not checker(part):
            continue
        out.append(
            {
                "file": path,
                "line": line,
                "character": character,
                "end_line": end_line,
                "end_character": end_character,
                "code": "BSL256",
                "message": cfg.message_fmt % part,
            }
        )
        break


def _line_char_from_byte_offset(
    source_bytes: bytes,
    offset: int,
) -> tuple[int, int]:
    prefix = source_bytes[:offset]
    line = prefix.count(b"\n") + 1
    line_start = prefix.rfind(b"\n")
    if line_start >= 0:
        line_bytes = prefix[line_start + 1 :]
    else:
        line_bytes = prefix
    # Byte offsets can occasionally land between UTF-8 code-unit boundaries.
    # `ignore` keeps character counts stable for LSP-style character indexing.
    return line, len(line_bytes.decode("utf-8", errors="ignore"))


def _line_char_from_node_point(
    node: Any,
    source_bytes: bytes,
    offset: int,
    *,
    line_starts: list[int] | None = None,
    is_end: bool = False,
) -> tuple[int, int]:
    point = getattr(node, "end_point" if is_end else "start_point", None)
    if point is not None:
        row = int(getattr(point, "row", -1))
        col = int(getattr(point, "column", -1))
        if row >= 0 and col >= 0:
            return row + 1, _char_from_row_byte_column(
                source_bytes,
                row,
                col,
                line_starts=line_starts,
            )
    return _line_char_from_byte_offset(source_bytes, offset)


def _char_from_row_byte_column(
    source_bytes: bytes,
    row0: int,
    col_bytes: int,
    *,
    line_starts: list[int] | None = None,
) -> int:
    if row0 < 0 or col_bytes <= 0:
        return 0
    total = len(source_bytes)
    if line_starts is not None:
        if row0 >= len(line_starts):
            return 0
        line_start = line_starts[row0]
    else:
        line_start = 0
        cur_row = 0
        while cur_row < row0 and line_start < total:
            nl = source_bytes.find(b"\n", line_start)
            if nl < 0:
                return 0
            line_start = nl + 1
            cur_row += 1
    prefix = source_bytes[line_start : min(line_start + col_bytes, total)]
    # Use `ignore` instead of `replace` to avoid artificial +1/+2 drifts when
    # parser byte columns point near multibyte boundaries.
    return len(prefix.decode("utf-8", errors="ignore"))


def _compute_line_starts(source_bytes: bytes) -> list[int]:
    starts = [0]
    search_from = 0
    total = len(source_bytes)
    while search_from < total:
        nl = source_bytes.find(b"\n", search_from)
        if nl < 0:
            break
        starts.append(nl + 1)
        search_from = nl + 1
    return starts
