from __future__ import annotations

from collections.abc import Callable
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.context import BsllsDocumentContext
from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.rules import (
    BsllsDiagnosticRule,
    CanonicalSpellingKeywordsRule,
    ConsecutiveEmptyLinesRule,
    DeprecatedFindRule,
    DeprecatedMessageRule,
    DeprecatedMethods8317Rule,
    EmptyStatementRule,
    ExtraCommasRule,
    MagicDateRule,
    NestedTernaryOperatorRule,
    SpaceAtStartCommentRule,
    UselessTernaryOperatorRule,
    UsingGotoRule,
    UsingHardcodeNetworkAddressRule,
    UsingHardcodePathRule,
    UsingServiceTagRule,
)
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic

_RULES: tuple[BsllsDiagnosticRule, ...] = (
    UsingHardcodeNetworkAddressRule(),
    UsingHardcodePathRule(),
    UsingServiceTagRule(),
    SpaceAtStartCommentRule(),
    EmptyStatementRule(),
    UsingGotoRule(),
    CanonicalSpellingKeywordsRule(),
    DeprecatedMessageRule(),
    NestedTernaryOperatorRule(),
    MagicDateRule(),
    ConsecutiveEmptyLinesRule(),
    DeprecatedFindRule(),
    DeprecatedMethods8317Rule(),
    ExtraCommasRule(),
    UselessTernaryOperatorRule(),
)
BSL_RUNTIME_RULE_CODES: frozenset[str] = frozenset(rule.code for rule in _RULES)


def append_bslls_runtime_rule_tasks(
    rule_tasks: list[tuple[str, Callable[[], list[Diagnostic]]]],
    *,
    engine: Any,
    path: str,
    content: str,
    lines: list[str],
    tree: Any,
    snapshot: Any | None,
) -> None:
    context = BsllsDocumentContext(
        path=path,
        content=content,
        lines=lines,
        tree=tree,
        snapshot=snapshot,
        max_bool_ops=int(getattr(engine, "max_bool_ops", 3)),
        bsl036_enabled=bool(engine._rule_enabled("BSL036")),
    )
    for rule in _RULES:
        if engine._rule_enabled(rule.code):
            rule_tasks.append((rule.code, lambda rule=rule: rule.run(context)))
