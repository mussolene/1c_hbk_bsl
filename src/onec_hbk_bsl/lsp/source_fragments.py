"""Utilities for LSP signature and argument text snippets."""

from __future__ import annotations

import re


def strip_leading_val_keywords(fragment: str) -> str:
    """Remove one or more leading ``Знач`` / ``Val`` keywords."""
    value = fragment.strip()
    while True:
        next_value = re.sub(r"^(?:Знач|Val)\s+", "", value, flags=re.IGNORECASE).strip()
        if next_value == value:
            return value
        value = next_value


def parameter_name_from_declaration_fragment(param_chunk: str) -> str:
    """Return the first identifier from one parameter declaration fragment."""
    value = param_chunk.strip()
    if not value:
        return ""
    value = value.lstrip("&").strip()
    value = strip_leading_val_keywords(value)
    value = value.split("=", 1)[0].strip()
    parts = value.split()
    return parts[0] if parts else ""


def split_commas_outside_double_quotes(segment: str) -> list[str]:
    """Split a signature/argument snippet on commas outside BSL string literals."""
    segment = segment.strip()
    if not segment:
        return []
    parts: list[str] = []
    buffer: list[str] = []
    in_string = False
    idx = 0
    while idx < len(segment):
        char = segment[idx]
        if in_string:
            if char == '"' and idx + 1 < len(segment) and segment[idx + 1] == '"':
                buffer.append('""')
                idx += 2
                continue
            if char == '"':
                in_string = False
            buffer.append(char)
            idx += 1
            continue
        if char == '"':
            in_string = True
            buffer.append(char)
            idx += 1
            continue
        if char == ",":
            piece = "".join(buffer).strip()
            if piece:
                parts.append(piece)
            buffer = []
            idx += 1
            continue
        buffer.append(char)
        idx += 1
    tail = "".join(buffer).strip()
    if tail:
        parts.append(tail)
    return parts
