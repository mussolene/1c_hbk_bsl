"""
Auto-fix engine for onec-hbk-bsl.

Applies safe, mechanical fixes to BSL source files in-place.

Supported rules
---------------
BSL009  SelfAssign              — delete the self-assignment line
BSL010  UselessReturn           — delete the redundant 'Возврат;' line
BSL055  ConsecutiveBlankLines   — truncate blank-line runs to MAX_BLANK_LINES (1)
BSL060  DoubleNegation          — replace 'НЕ НЕ expr' with 'expr'

Usage
-----
From the CLI (--fix flag)::

    onec-hbk-bsl --check . --fix

Programmatic::

    from onec_hbk_bsl.analysis.fix_engine import apply_fixes, FIXABLE_RULES
    result = apply_fixes("/path/to/file.bsl", diagnostics)
    print(result.applied, result.skipped)
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostics import Diagnostic

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

FixFn = Callable[[list[str], Diagnostic], list[str] | None]
"""
Signature for a single-rule fixer.

Args:
    lines:      The current source lines (mutable copy, do not share).
    diagnostic: The diagnostic to fix.

Returns:
    Updated lines list if the fix was applied, or ``None`` to skip.
"""


@dataclass
class FixResult:
    """Result of an `apply_fixes` call for one file."""

    file: str
    applied: list[str] = field(default_factory=list)   # rule codes fixed
    skipped: list[str] = field(default_factory=list)   # skipped (unsafe/unknown)
    error: str | None = None                           # I/O error message


# ---------------------------------------------------------------------------
# Individual fixer functions
# ---------------------------------------------------------------------------

_MAX_BLANK_LINES = 1

# Regex for a plain empty return (matches the useless-return rule's target)
_RE_EMPTY_RETURN = re.compile(r'^\s*(?:Возврат|Return)\s*;?\s*$', re.IGNORECASE)

# Regex for double negation
_RE_DOUBLE_NEG = re.compile(
    r'\b((?:НЕ|Not)\s+(?:НЕ|Not)\s+)',
    re.IGNORECASE,
)


def _fix_bsl009_self_assign(lines: list[str], diag: Diagnostic) -> list[str] | None:
    """Delete the line containing the self-assignment."""
    idx = diag.line - 1  # convert to 0-based
    if idx < 0 or idx >= len(lines):
        return None
    new_lines = lines[:idx] + lines[idx + 1:]
    return new_lines


def _fix_bsl010_useless_return(lines: list[str], diag: Diagnostic) -> list[str] | None:
    """Delete the redundant bare 'Возврат;' line."""
    idx = diag.line - 1
    if idx < 0 or idx >= len(lines):
        return None
    if not _RE_EMPTY_RETURN.match(lines[idx]):
        return None  # safety re-check
    return lines[:idx] + lines[idx + 1:]


def _fix_bsl055_consecutive_blank_lines(
    lines: list[str], diag: Diagnostic
) -> list[str] | None:
    """Truncate a run of blank lines to MAX_BLANK_LINES."""
    # The diagnostic line (1-based) points to the start of the blank run
    start = diag.line - 1  # 0-based
    if start < 0 or start >= len(lines):
        return None
    # Count the actual blank run
    end = start
    while end < len(lines) and not lines[end].strip():
        end += 1
    run_length = end - start
    if run_length <= _MAX_BLANK_LINES:
        return None  # nothing to do
    # Keep only MAX_BLANK_LINES blank lines from the run
    new_lines = lines[:start] + lines[start: start + _MAX_BLANK_LINES] + lines[end:]
    return new_lines


def _fix_bsl060_double_negation(lines: list[str], diag: Diagnostic) -> list[str] | None:
    """Replace 'НЕ НЕ expr' with 'expr' on the diagnostic line."""
    idx = diag.line - 1
    if idx < 0 or idx >= len(lines):
        return None
    original = lines[idx]
    # Strip one НЕ НЕ pair (the regex matches the doubled operator including trailing space)
    fixed, count = _RE_DOUBLE_NEG.subn("", original, count=1)
    if count == 0:
        return None
    new_lines = list(lines)
    new_lines[idx] = fixed
    return new_lines


# ---------------------------------------------------------------------------
# Fixer registry
# ---------------------------------------------------------------------------

FIXABLE_RULES: dict[str, FixFn] = {
    "BSL009": _fix_bsl009_self_assign,
    "BSL010": _fix_bsl010_useless_return,
    "BSL055": _fix_bsl055_consecutive_blank_lines,
    "BSL060": _fix_bsl060_double_negation,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_fixes(
    file_path: str,
    diagnostics: list[Diagnostic],
) -> FixResult:
    """
    Apply all fixable diagnostics to *file_path* in-place.

    Reads the file once, applies fixes in reverse line order (to preserve
    indices for earlier lines), and writes the result atomically.

    Args:
        file_path:    Absolute path to the BSL source file.
        diagnostics:  All diagnostics for this file (may include unfixable ones).

    Returns:
        :class:`FixResult` with counts of applied/skipped fixes.
    """
    result = FixResult(file=file_path)

    # Separate fixable from unfixable
    fixable = [(d, FIXABLE_RULES[d.code]) for d in diagnostics if d.code in FIXABLE_RULES]
    result.skipped = [d.code for d in diagnostics if d.code not in FIXABLE_RULES]

    if not fixable:
        return result

    # Read source
    try:
        raw = Path(file_path).read_bytes()
    except OSError as exc:
        result.error = str(exc)
        return result

    # Detect BOM and line ending style
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    content = raw.decode("utf-8-sig", errors="replace")
    crlf = "\r\n" in content

    # Split preserving newlines-style awareness
    lines = content.splitlines()
    # Ensure last line has no trailing newline issue when reconstructing
    had_trailing_newline = content.endswith(("\n", "\r\n"))

    # Sort fixable diagnostics in reverse line order (bottom → top) to
    # preserve line indices when lines are deleted or modified above
    fixable_sorted = sorted(fixable, key=lambda x: x[0].line, reverse=True)

    consumed_lines: set[int] = set()  # 0-based indices fully consumed by a fix

    for diag, fix_fn in fixable_sorted:
        idx = diag.line - 1
        if idx in consumed_lines:
            result.skipped.append(diag.code)
            continue
        updated = fix_fn(list(lines), diag)
        if updated is None:
            result.skipped.append(diag.code)
            continue
        # Mark all lines that were removed (by comparing lengths)
        if len(updated) < len(lines):
            # A line was deleted — mark the deleted index(es) as consumed
            for removed in range(len(updated), len(lines)):
                consumed_lines.add(removed)
        lines = updated
        result.applied.append(diag.code)

    # Reconstruct content
    nl = "\r\n" if crlf else "\n"
    new_content = nl.join(lines)
    if had_trailing_newline:
        new_content += nl

    if has_bom:
        new_bytes = b"\xef\xbb\xbf" + new_content.encode("utf-8")
    else:
        new_bytes = new_content.encode("utf-8")

    # Atomic write via temp file in same directory
    dir_path = os.path.dirname(file_path) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path, prefix=".bsl-fix-", suffix=".tmp"
        )
        try:
            os.write(fd, new_bytes)
        finally:
            os.close(fd)
        os.replace(tmp_path, file_path)
    except OSError as exc:
        result.error = str(exc)
        # Try to clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return result
