from __future__ import annotations

from onec_hbk_bsl.analysis.diagnostic.models import RuleDefinition, RuleLocale


def render_rule_message(identifier: str, *args: object, locale: RuleLocale = "ru") -> str:
    """Render a catalog template, rejecting missing or extra interpolation values."""
    rule = get_rule(identifier, locale=locale)
    template = rule.message_template
    expected = template.count("%s")
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
        return RuleDefinition(
            code=code,
            name=name,
            description=english_description,
            message_template=english_description,
            message=english_description,
            severity=severity,
            tags=tags,
            implemented=implemented,
            locale=locale,
        )

    description = RULE_DESCRIPTIONS_RU.get(code) or english_description
    message_template = RULE_MESSAGES_RU.get(code) or description
    # Diagnostics without structured interpolation values must never leak raw
    # ``%s`` placeholders to CLI/LSP/MCP consumers.
    message = description if "%s" in message_template else message_template
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
