from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

RE_HAS_DIGIT = re.compile(r"\d")


def _is_latin_letter(ch: str) -> bool:
    if not ch.isalpha():
        return False
    return "LATIN" in unicodedata.name(ch, "")


def _is_cyrillic_letter(ch: str) -> bool:
    if not ch.isalpha():
        return False
    return "CYRILLIC" in unicodedata.name(ch, "")


def contains_latin_letter(text: str) -> bool:
    return any(_is_latin_letter(ch) for ch in text)


def contains_cyrillic_letter(text: str) -> bool:
    return any(_is_cyrillic_letter(ch) for ch in text)


def all_alpha_upper(fragment: str) -> bool:
    letters = [c for c in fragment if c.isalpha()]
    return bool(letters) and all(x.isupper() for x in letters)


def fragment_needs_ru_typo_scan(fragment: str) -> bool:
    if RE_HAS_DIGIT.search(fragment):
        return False
    if not contains_cyrillic_letter(fragment):
        return False
    # All-caps short tokens are usually abbreviations: ОКВЭД, НДС, XML-like BSL names.
    if len(fragment) >= 2 and all_alpha_upper(fragment):
        return False
    return True


def _java_letter_bucket(ch: str) -> str:
    """Bucket compatible with Apache ``splitByCharacterTypeCamelCase``."""
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


@lru_cache(maxsize=100_000)
def split_by_character_type_camel_case(text: str) -> list[str]:
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
