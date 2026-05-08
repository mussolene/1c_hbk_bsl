from __future__ import annotations

from collections.abc import Callable
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.context import BsllsDocumentContext
from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.rules import (
    BsllsDiagnosticRule,
    CanonicalSpellingKeywordsRule,
    ConsecutiveEmptyLinesRule,
    DeprecatedCurrentDateRule,
    DeprecatedFindRule,
    DeprecatedMessageRule,
    DeprecatedMethods8310Rule,
    DeprecatedMethods8317Rule,
    DeprecatedTypeManagedFormRule,
    DisableSafeModeRule,
    DoubleNegativesRule,
    EmptyStatementRule,
    ExecuteExternalCodeInCommonModuleRule,
    ExecuteExternalCodeRule,
    ExternalAppStartingRule,
    ExtraCommasRule,
    FileSystemAccessRule,
    GetFormMethodRule,
    InternetAccessRule,
    IsInRoleMethodRule,
    MagicDateRule,
    NestedTernaryOperatorRule,
    OSUsersMethodRule,
    SetPrivilegedModeRule,
    SpaceAtStartCommentRule,
    TempFilesDirRule,
    UselessTernaryOperatorRule,
    UseSystemInformationRule,
    UsingExternalCodeToolsRule,
    UsingGotoRule,
    UsingHardcodeNetworkAddressRule,
    UsingHardcodePathRule,
    UsingServiceTagRule,
    UsingSynchronousCallsRule,
    VirtualTableCallWithoutParametersRule,
)
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic

_RULES: tuple[BsllsDiagnosticRule, ...] = (
    UsingHardcodeNetworkAddressRule(),
    UsingHardcodePathRule(),
    UsingServiceTagRule(),
    SpaceAtStartCommentRule(),
    EmptyStatementRule(),
    UsingGotoRule(),
    DoubleNegativesRule(),
    CanonicalSpellingKeywordsRule(),
    DeprecatedMessageRule(),
    NestedTernaryOperatorRule(),
    MagicDateRule(),
    ConsecutiveEmptyLinesRule(),
    DeprecatedFindRule(),
    DeprecatedCurrentDateRule(),
    DeprecatedMethods8310Rule(),
    DeprecatedMethods8317Rule(),
    GetFormMethodRule(),
    DeprecatedTypeManagedFormRule(),
    DisableSafeModeRule(),
    ExecuteExternalCodeRule(),
    ExecuteExternalCodeInCommonModuleRule(),
    ExternalAppStartingRule(),
    FileSystemAccessRule(),
    InternetAccessRule(),
    IsInRoleMethodRule(),
    UseSystemInformationRule(),
    OSUsersMethodRule(),
    SetPrivilegedModeRule(),
    TempFilesDirRule(),
    UsingExternalCodeToolsRule(),
    UsingSynchronousCallsRule(),
    VirtualTableCallWithoutParametersRule(),
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
