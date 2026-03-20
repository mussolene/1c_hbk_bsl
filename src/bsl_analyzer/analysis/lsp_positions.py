"""
LSP position helpers.

Tree-sitter reports ``Point.column`` as a UTF-8 *byte* offset within the line.
The Language Server Protocol (and VS Code) use UTF-16 code unit offsets for
``Position.character``. Mixing a byte-based start with ``len(name)`` in Unicode
code points breaks ranges for Cyrillic identifiers (e.g. half-dimmed dead-code).
"""

from __future__ import annotations


def utf8_byte_offset_to_lsp_character(line: str, byte_col: int) -> int:
    """Map Tree-sitter column (UTF-8 byte index in *line*) to LSP character (UTF-16 units)."""
    if not line or byte_col <= 0:
        return 0
    raw = line.encode("utf-8")
    if byte_col >= len(raw):
        return utf16_len(line)
    prefix = raw[:byte_col].decode("utf-8", errors="replace")
    return utf16_len(prefix)


def utf16_len(text: str) -> int:
    """Length of *text* in UTF-16 code units (LSP ``character`` delta for BMP+surrogates)."""
    return len(text.encode("utf-16-le")) // 2
