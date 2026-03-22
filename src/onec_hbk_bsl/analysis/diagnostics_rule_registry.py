"""
How diagnostic rules are *invoked* (phase / data needs) — registry + heuristics.

This module does **not** run rules; :class:`DiagnosticEngine` keeps the real call chain.
The snapshot is attached to ``last_metrics["rule_invoke"]`` for benchmarks, UI, and
future scheduling (e.g. parallel phase batches) without a second source of truth in
separate batch files.

Contract
--------
- **Explicit** entries in :data:`_EXPLICIT_PHASE` win.
- Otherwise :func:`infer_rule_invoke` uses ``RULE_METADATA`` tags/name heuristics.
- Unknown codes still get a phase (usually :attr:`RulePhase.OTHER`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "RulePhase",
    "RuleInvokeInfo",
    "infer_rule_invoke",
    "build_enabled_invoke_snapshot",
    "parallel_phase_groups",
]


class RulePhase(StrEnum):
    """Preferred execution / data shape for a rule (not BSLLS categories)."""

    LINE = "line"  # scan ``lines`` / line-oriented regex
    CST = "cst"  # tree-sitter CST when available
    PROC = "proc"  # procedure / method boundaries (``procs``)
    REGION = "region"  # ``#Область`` / regions
    INDEX = "index"  # symbol index or metadata index
    HYBRID = "hybrid"  # CST first, regex fallback (typical in this codebase)
    MODULE = "module"  # whole-file / header semantics
    OTHER = "other"  # mixed or not yet classified


# Rules that are clearly CST+regex or CST-only in the engine — keep tight; rest uses tags.
_EXPLICIT_PHASE: dict[str, RulePhase] = {
    "BSL001": RulePhase.CST,
    "BSL004": RulePhase.HYBRID,
    "BSL009": RulePhase.HYBRID,
    "BSL014": RulePhase.LINE,
    "BSL016": RulePhase.REGION,
    "BSL018": RulePhase.HYBRID,
    "BSL033": RulePhase.HYBRID,
    "BSL038": RulePhase.HYBRID,
    "BSL051": RulePhase.HYBRID,
    "BSL052": RulePhase.HYBRID,
    "BSL059": RulePhase.HYBRID,
    "BSL060": RulePhase.HYBRID,
    "BSL061": RulePhase.HYBRID,
    "BSL062": RulePhase.HYBRID,
    "BSL070": RulePhase.HYBRID,
    "BSL085": RulePhase.HYBRID,
    "BSL091": RulePhase.HYBRID,
    "BSL092": RulePhase.HYBRID,
    "BSL119": RulePhase.LINE,
    "BSL120": RulePhase.LINE,
    "BSL121": RulePhase.LINE,
    "BSL280": RulePhase.INDEX,
}


@dataclass(frozen=True, slots=True)
class RuleInvokeInfo:
    phase: RulePhase
    source: str  # "explicit" | "tags" | "default"


def infer_rule_invoke(code: str, meta: dict[str, Any] | None) -> RuleInvokeInfo:
    """Classify a rule code; *meta* is typically ``RULE_METADATA[code]``."""
    if code in _EXPLICIT_PHASE:
        return RuleInvokeInfo(_EXPLICIT_PHASE[code], "explicit")

    tags = frozenset((meta or {}).get("tags") or [])
    name = str((meta or {}).get("name", ""))
    sonar = str((meta or {}).get("sonar_type", ""))

    if "syntax" in tags or name == "ParseError":
        return RuleInvokeInfo(RulePhase.CST, "tags")
    if "complexity" in tags or "brain-overload" in tags or name in (
        "MethodSize",
        "CognitiveComplexity",
        "CyclomaticComplexity",
    ):
        return RuleInvokeInfo(RulePhase.PROC, "tags")
    if "api" in tags or "region" in name.lower() or "Region" in name:
        return RuleInvokeInfo(RulePhase.REGION, "tags")
    if "security" in tags or "vulnerability" in sonar.lower():
        return RuleInvokeInfo(RulePhase.LINE, "tags")
    if "convention" in tags or name in ("LineLength", "TrailingSpaces"):
        return RuleInvokeInfo(RulePhase.LINE, "tags")
    if "unused" in tags or "redundant" in tags:
        return RuleInvokeInfo(RulePhase.PROC, "tags")
    if "error-handling" in tags or "EmptyCodeBlock" in name:
        return RuleInvokeInfo(RulePhase.HYBRID, "tags")

    return RuleInvokeInfo(RulePhase.OTHER, "default")


def build_enabled_invoke_snapshot(
    engine: Any,
    rule_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Enabled rules only: counts and codes grouped by inferred :class:`RulePhase`.

    *engine* must implement ``_rule_enabled(code: str) -> bool``.
    """
    by_phase: dict[str, list[str]] = {}
    for code, meta in rule_metadata.items():
        if not engine._rule_enabled(code):
            continue
        info = infer_rule_invoke(code, meta)
        by_phase.setdefault(info.phase.value, []).append(code)
    for lst in by_phase.values():
        lst.sort()
    return {
        "counts_by_phase": {p: len(c) for p, c in sorted(by_phase.items())},
        "codes_by_phase": by_phase,
    }


# Phases that are safe to schedule concurrently with each other **once** invokers exist
# (read-only shared trees/lines). Engine does not use this yet — for orchestration work.
parallel_phase_groups: tuple[frozenset[RulePhase], ...] = (
    frozenset({RulePhase.LINE, RulePhase.CST}),
)
