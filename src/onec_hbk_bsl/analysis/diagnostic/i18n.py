from __future__ import annotations

import re

from onec_hbk_bsl.analysis.diagnostic.models import RuleDefinition, RuleLocale


def render_rule_message(
    identifier: str, *args: object, locale: RuleLocale = "ru", variant: str = ""
) -> str:
    """Render a catalog template, rejecting missing or extra interpolation values."""
    rule = get_rule(identifier, locale=locale)
    template = rule.message_template
    if variant:
        from onec_hbk_bsl.analysis.diagnostics import RULE_MESSAGES_EN, RULE_MESSAGES_RU

        templates = RULE_MESSAGES_EN if locale == "en" else RULE_MESSAGES_RU
        template = templates[f"{rule.code}.{variant}"]
    if locale == "en" and args:
        if rule.code == "BSL216":
            sides = {
                "Слева": "To the left",
                "Справа": "To the right",
                "Слева и справа": "Left and right",
            }
            args = (sides.get(str(args[0]), args[0]), *args[1:])
        elif (
            rule.code == "BSL176"
            and len(args) == 2
            and str(args[1]).startswith(" Следует использовать: ")
        ):
            args = (args[0], str(args[1]).replace(" Следует использовать: ", " Use instead: ", 1))
        elif rule.code == "BSL224":
            kinds = {"метода": "method", "конструктора": "constructor"}
            args = (kinds.get(str(args[0]), args[0]), *args[1:])
    expected = sum(placeholder != "%%" for placeholder in re.findall(r"%(?:%|s|d)", template))
    if len(args) != expected:
        raise ValueError(f"{rule.code} message expects {expected} argument(s), got {len(args)}")
    if not args:
        return template
    try:
        return template % args
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{rule.code} message arguments are invalid") from exc


def get_rule(identifier: str, *, locale: RuleLocale = "ru") -> RuleDefinition:
    """
    Return the complete rule definition for ``BSL###`` code or BSLLS name.

    Diagnostic rules should emit a stable code and source range. Presentation
    layers use this catalog to resolve name, description, message, severity,
    tags, and implementation status from one place.
    """
    from onec_hbk_bsl.analysis.diagnostics import (
        _CODE_TO_PRIMARY_BSLLS_NAME,
        RULE_DESCRIPTIONS_RU,
        RULE_MESSAGES_EN,
        RULE_MESSAGES_RU,
        RULE_METADATA,
        resolve_rule_token_to_code,
    )

    raw_identifier = (identifier or "").strip()
    code = resolve_rule_token_to_code(raw_identifier) or raw_identifier
    meta = RULE_METADATA.get(code, {})
    name = _CODE_TO_PRIMARY_BSLLS_NAME.get(code) or str(meta.get("name") or code)
    english_description = str(meta.get("description") or meta.get("name") or code)
    severity = str(meta.get("severity") or "")
    tags = tuple(str(tag) for tag in (meta.get("tags") or ()))
    from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.runner import (
        DIAGNOSTIC_RUNTIME_RULE_CODES,
    )

    implemented = code in DIAGNOSTIC_RUNTIME_RULE_CODES

    if locale == "en":
        template = RULE_MESSAGES_EN.get(code) or english_description
        return RuleDefinition(
            code=code,
            name=name,
            description=english_description,
            message_template=template,
            message=english_description if re.search(r"%[sd]", template) else template,
            severity=severity,
            tags=tags,
            implemented=implemented,
            locale=locale,
        )

    description = RULE_DESCRIPTIONS_RU.get(code) or english_description
    message_template = RULE_MESSAGES_RU.get(code) or description
    # Diagnostics without structured interpolation values must never leak raw
    # Interpolation placeholders must not reach CLI/LSP/MCP consumers.
    message = description if re.search(r"%[sd]", message_template) else message_template
    return RuleDefinition(
        code=code,
        name=name,
        description=description,
        message_template=message_template,
        message=message,
        severity=severity,
        tags=tags,
        implemented=implemented,
        locale=locale,
    )
