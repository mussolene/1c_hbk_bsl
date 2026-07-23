"""Deterministic, exact-span symbol rename planning and transactional commit."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
from onec_hbk_bsl.analysis.lsp_positions import (
    utf8_byte_offset_to_lsp_character,
    utf16_len,
)
from onec_hbk_bsl.parser.bsl_parser import BslParser

_IDENTIFIER_RE = re.compile(r"^[А-ЯЁа-яёA-Za-z_]\w*$", re.UNICODE)
_METHOD_KINDS = frozenset({"procedure", "function"})
_DEFINITION_PARENTS = frozenset({"procedure_definition", "function_definition"})


class RenameIndex(Protocol):
    """Index operations required by :func:`build_rename_plan`."""

    def find_symbol(self, name: str, limit: int = 20) -> list[dict[str, Any]]: ...

    def find_callers(
        self,
        callee_name: str,
        limit: int | None = 50,
        scope_file: str | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, order=True)
class RenameEdit:
    """One proven identifier span in a source file."""

    start_byte: int
    end_byte: int
    start_line: int
    start_character: int
    end_line: int
    end_character: int
    old_text: str
    new_text: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_line": self.start_line,
            "start_character": self.start_character,
            "end_line": self.end_line,
            "end_character": self.end_character,
            "old_text": self.old_text,
            "new_text": self.new_text,
        }


@dataclass(frozen=True)
class RenameFilePlan:
    """Edits and optimistic-concurrency precondition for one file."""

    file_path: str
    content_sha256: str
    has_utf8_bom: bool
    edits: tuple[RenameEdit, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "content_sha256": self.content_sha256,
            "edits": [edit.as_dict() for edit in self.edits],
        }


@dataclass(frozen=True)
class RenamePlan:
    """Immutable cross-surface rename plan."""

    old_name: str
    new_name: str
    files: tuple[RenameFilePlan, ...]

    @property
    def total_occurrences(self) -> int:
        return sum(len(file.edits) for file in self.files)

    def as_dict(self) -> dict[str, Any]:
        return {
            "old_name": self.old_name,
            "new_name": self.new_name,
            "files_affected": len(self.files),
            "total_occurrences": self.total_occurrences,
            "files": [file.as_dict() for file in self.files],
        }


class RenameRefused(ValueError):
    """Stable refusal raised before any file is changed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": str(self)}}


@dataclass(frozen=True)
class _Source:
    path: str
    text: str
    raw: bytes
    has_utf8_bom: bool


@dataclass(frozen=True)
class _Occurrence:
    kind: str
    qualified: bool
    edit: RenameEdit


def is_bsl_identifier(value: str) -> bool:
    """Return whether *value* is a syntactically valid BSL identifier."""
    return bool(_IDENTIFIER_RE.fullmatch(value))


def _canonical_path(path: str | Path) -> str:
    return str(Path(path).resolve())


def _source_from_bytes(path: str, raw: bytes) -> _Source:
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    payload = raw[3:] if has_bom else raw
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenameRefused("unsupported_encoding", f"{path}: expected UTF-8 source") from exc
    return _Source(path=path, text=text, raw=raw, has_utf8_bom=has_bom)


def _load_source(path: str, override: str | None) -> _Source:
    if override is not None:
        raw = override.encode("utf-8")
        return _Source(path=path, text=override, raw=raw, has_utf8_bom=False)
    try:
        return _source_from_bytes(path, Path(path).read_bytes())
    except OSError as exc:
        raise RenameRefused("source_unavailable", f"{path}: {exc}") from exc


def _node_text(node: Any) -> str:
    value = getattr(node, "text", "")
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _is_qualified_method_call(node: Any) -> bool:
    parent = getattr(node, "parent", None)
    if parent is None or getattr(parent, "type", "") != "method_call":
        return False
    call_expression = getattr(parent, "parent", None)
    if call_expression is None or getattr(call_expression, "type", "") != "call_expression":
        return False
    return any(
        getattr(child, "type", "") == "." and child.end_byte <= parent.start_byte
        for child in getattr(call_expression, "children", ()) or ()
    )


def _collect_occurrences(source: _Source, old_name: str, new_name: str) -> list[_Occurrence]:
    tree = BslParser().parse_content(source.text, file_path=source.path)
    root = getattr(tree, "root_node", None)
    if root is None:
        raise RenameRefused("parser_unavailable", f"{source.path}: CST is unavailable")

    lines = source.text.splitlines()
    old_fold = old_name.casefold()
    occurrences: list[_Occurrence] = []

    def visit(node: Any, parent_type: str = "") -> None:
        node_type = getattr(node, "type", "")
        if node_type == "identifier" and _node_text(node).casefold() == old_fold:
            kind = ""
            qualified = False
            if parent_type in _DEFINITION_PARENTS:
                kind = "definition"
            elif parent_type == "method_call":
                kind = "call"
                qualified = _is_qualified_method_call(node)
            if kind:
                line = int(node.start_point[0])
                line_text = lines[line] if 0 <= line < len(lines) else ""
                start_character = utf8_byte_offset_to_lsp_character(
                    line_text, int(node.start_point[1])
                )
                text = _node_text(node)
                occurrences.append(
                    _Occurrence(
                        kind=kind,
                        qualified=qualified,
                        edit=RenameEdit(
                            start_byte=int(node.start_byte),
                            end_byte=int(node.end_byte),
                            start_line=line,
                            start_character=start_character,
                            end_line=line,
                            end_character=start_character + utf16_len(text),
                            old_text=text,
                            new_text=new_name,
                        ),
                    )
                )
        for child in getattr(node, "children", ()) or ():
            visit(child, node_type)

    visit(root)
    return occurrences


def _live_method_definitions(path: str, source: _Source) -> list[dict[str, Any]]:
    facts = build_document_snapshot(path, content=source.text).semantic_facts()
    return [
        {
            "name": symbol.name,
            "kind": symbol.kind,
            "file_path": path,
            "line": symbol.line,
            "character": symbol.character,
            "is_export": symbol.is_export,
        }
        for symbol in facts.symbols
        if symbol.kind in _METHOD_KINDS
    ]


def build_rename_plan(
    index: RenameIndex,
    old_name: str,
    new_name: str,
    *,
    content_overrides: Mapping[str, str] | None = None,
    path_validator: Callable[[str], str] | None = None,
) -> RenamePlan:
    """Build a deterministic exact-span plan or refuse before any write."""
    if not is_bsl_identifier(old_name) or not is_bsl_identifier(new_name):
        raise RenameRefused("invalid_identifier", "Both rename names must be valid identifiers")
    if old_name == new_name:
        raise RenameRefused("no_change", "The new name is equal to the current name")

    overrides = {
        _canonical_path(path): content for path, content in (content_overrides or {}).items()
    }
    indexed_definitions = [
        dict(row)
        for row in index.find_symbol(old_name, limit=1001)
        if row.get("kind") in _METHOD_KINDS
    ]
    for path in overrides:
        indexed_definitions = [
            row for row in indexed_definitions if _canonical_path(str(row["file_path"])) != path
        ]
        source = _load_source(path, overrides[path])
        indexed_definitions.extend(_live_method_definitions(path, source))

    definitions = [
        row
        for row in indexed_definitions
        if str(row.get("name", "")).casefold() == old_name.casefold()
    ]
    definitions.sort(
        key=lambda row: (
            _canonical_path(str(row["file_path"])).casefold(),
            _canonical_path(str(row["file_path"])),
            int(row.get("line", 0)),
            int(row.get("character", 0)),
        )
    )
    if not definitions:
        return RenamePlan(old_name=old_name, new_name=new_name, files=())
    if len(definitions) != 1:
        raise RenameRefused(
            "ambiguous_definition",
            f"{old_name}: expected one semantic definition, found {len(definitions)}",
        )

    collisions: list[dict[str, Any]] = []
    if old_name.casefold() != new_name.casefold():
        collisions = [
            row for row in index.find_symbol(new_name, limit=2) if row.get("kind") in _METHOD_KINDS
        ]
        for path, content in overrides.items():
            source = _load_source(path, content)
            collisions = [
                row for row in collisions if _canonical_path(str(row["file_path"])) != path
            ]
            collisions.extend(
                row
                for row in _live_method_definitions(path, source)
                if str(row["name"]).casefold() == new_name.casefold()
            )
    if collisions:
        raise RenameRefused("name_collision", f"{new_name}: method definition already exists")

    definition = definitions[0]
    definition_path = _canonical_path(str(definition["file_path"]))
    scope_file = definition_path if not bool(definition.get("is_export")) else None
    callers = index.find_callers(old_name, limit=None, scope_file=scope_file)

    relevant_paths = {definition_path, *overrides}
    relevant_paths.update(_canonical_path(str(row["caller_file"])) for row in callers)
    if path_validator is not None:
        relevant_paths = {path_validator(path) for path in relevant_paths}

    callers_by_path: dict[str, set[tuple[int, int]]] = {}
    for row in callers:
        path = _canonical_path(str(row["caller_file"]))
        if path_validator is not None:
            path = path_validator(path)
        callers_by_path.setdefault(path, set()).add(
            (max(0, int(row["caller_line"]) - 1), int(row.get("caller_character", 0) or 0))
        )

    file_plans: list[RenameFilePlan] = []
    for path in sorted(relevant_paths, key=lambda value: (value.casefold(), value)):
        source = _load_source(path, overrides.get(path))
        occurrences = _collect_occurrences(source, old_name, new_name)
        if any(item.kind == "call" and item.qualified for item in occurrences):
            raise RenameRefused(
                "receiver_ambiguity",
                f"{path}: qualified call cannot be linked to a bare-name definition",
            )

        definitions_in_file = [item for item in occurrences if item.kind == "definition"]
        if path == definition_path:
            if len(definitions_in_file) != 1:
                raise RenameRefused(
                    "stale_index",
                    f"{path}: indexed definition does not match current content",
                )
        elif definitions_in_file:
            raise RenameRefused(
                "ambiguous_definition",
                f"{path}: additional live definition of {old_name} found",
            )

        direct_calls = [item for item in occurrences if item.kind == "call"]
        if path not in overrides:
            parsed_positions = {
                (item.edit.start_line, item.edit.start_character) for item in direct_calls
            }
            if parsed_positions != callers_by_path.get(path, set()):
                raise RenameRefused(
                    "stale_index",
                    f"{path}: indexed call sites do not match current content",
                )

        edits = tuple(
            sorted(
                (item.edit for item in occurrences),
                key=lambda edit: (edit.start_byte, edit.end_byte),
            )
        )
        if edits:
            file_plans.append(
                RenameFilePlan(
                    file_path=path,
                    content_sha256=hashlib.sha256(source.raw).hexdigest(),
                    has_utf8_bom=source.has_utf8_bom,
                    edits=edits,
                )
            )

    return RenamePlan(old_name=old_name, new_name=new_name, files=tuple(file_plans))


def _render_file(file_plan: RenameFilePlan, raw: bytes) -> bytes:
    source = _source_from_bytes(file_plan.file_path, raw)
    payload = source.text.encode("utf-8")
    for edit in reversed(file_plan.edits):
        current = payload[edit.start_byte : edit.end_byte].decode("utf-8")
        if current.casefold() != edit.old_text.casefold():
            raise RenameRefused(
                "stale_content",
                f"{file_plan.file_path}: planned span no longer contains {edit.old_text}",
            )
        payload = (
            payload[: edit.start_byte] + edit.new_text.encode("utf-8") + payload[edit.end_byte :]
        )
    return (b"\xef\xbb\xbf" if file_plan.has_utf8_bom else b"") + payload


def _stage_bytes(path: Path, raw: bytes, mode: int) -> Path:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.rename-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, stat.S_IMODE(mode))
        return temp_path
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _replace_path(source: Path, destination: Path) -> None:
    """Replace hook kept separate so rollback behavior can be failure-injected."""
    os.replace(source, destination)


def commit_rename_plan(plan: RenamePlan) -> None:
    """Apply all files atomically as a transaction, restoring bytes on failure."""
    originals: dict[Path, bytes] = {}
    modes: dict[Path, int] = {}
    rendered: dict[Path, bytes] = {}
    staged: dict[Path, Path] = {}
    replaced: list[Path] = []

    for file_plan in plan.files:
        path = Path(file_plan.file_path)
        try:
            raw = path.read_bytes()
            mode = path.stat().st_mode
        except OSError as exc:
            raise RenameRefused("source_unavailable", f"{path}: {exc}") from exc
        if hashlib.sha256(raw).hexdigest() != file_plan.content_sha256:
            raise RenameRefused("stale_content", f"{path}: content hash changed")
        originals[path] = raw
        modes[path] = mode
        rendered[path] = _render_file(file_plan, raw)

    try:
        for path in sorted(rendered, key=lambda value: (str(value).casefold(), str(value))):
            staged[path] = _stage_bytes(path, rendered[path], modes[path])
        for path in sorted(staged, key=lambda value: (str(value).casefold(), str(value))):
            _replace_path(staged[path], path)
            replaced.append(path)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for path in reversed(replaced):
            try:
                rollback = _stage_bytes(path, originals[path], modes[path])
                os.replace(rollback, path)
            except BaseException as rollback_exc:  # pragma: no cover - catastrophic FS failure
                rollback_errors.append(f"{path}: {rollback_exc}")
        message = f"Rename transaction failed: {exc}"
        if rollback_errors:
            message += f"; rollback failed: {'; '.join(rollback_errors)}"
        raise RenameRefused("commit_failed", message) from exc
    finally:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)
