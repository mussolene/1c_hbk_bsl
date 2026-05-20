from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CandidateKind = Literal["string", "code", "method"]


@dataclass(frozen=True, slots=True)
class BslTypoConfig:
    message_fmt: str
    language_short: str
    words_to_ignore: frozenset[str]
    min_word_length: int = 3


@dataclass(frozen=True, slots=True)
class SpellCandidate:
    text: str
    line: int
    character: int
    end_line: int
    end_character: int
    kind: CandidateKind
    exact_ignore: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SpellIssue:
    word: str
    candidate: SpellCandidate
