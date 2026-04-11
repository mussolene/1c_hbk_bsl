from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
from onec_hbk_bsl.indexer.metadata_parser import crawl_config
from onec_hbk_bsl.indexer.metadata_registry import FOLDER_TO_KIND

_RE_XML_BOOL_SIMPLE = r"<{tag}>\s*(true|false)\s*</{tag}>"
_RE_BSL275_HANDLER = re.compile(r"<Handler>\s*([^<]*)\s*</Handler>", re.IGNORECASE)
_RE_BSL278_PROCNAME = re.compile(r"<ProcedureName>\s*([^<]*)\s*</ProcedureName>", re.IGNORECASE)
_RE_XML_NAME_SIMPLE = re.compile(r"<Name>\s*([^<]+?)\s*</Name>", re.IGNORECASE)
_RE_XML_DIMENSION_BLOCK = re.compile(
    r"<Dimension\b.*?>.*?<Name>\s*([^<]+?)\s*</Name>.*?<DenyIncompleteValues>\s*(true|false)\s*</DenyIncompleteValues>.*?</Dimension>",
    re.IGNORECASE | re.DOTALL,
)
_RE_XML_SET_FOR_NEW_OBJECTS = re.compile(
    r"<SetForNewObjects>\s*(true|false)\s*</SetForNewObjects>",
    re.IGNORECASE,
)
_RE_XML_METHOD_NAME = re.compile(r"<MethodName>\s*([^<]+?)\s*</MethodName>", re.IGNORECASE)
_RE_XML_EVENT_HANDLER = re.compile(
    r"<Handler>\s*([^<]+?)\s*</Handler>|<Method>\s*([^<]+?)\s*</Method>",
    re.IGNORECASE,
)
_RE_XML_DATAPATH = re.compile(r"<DataPath>\s*([^<]+?)\s*</DataPath>", re.IGNORECASE)
_RE_XML_PROTECTED = re.compile(
    r"<(?:IsProtected|Protected)>\s*true\s*</(?:IsProtected|Protected)>", re.IGNORECASE
)
_RE_XML_PRIVILEGED = re.compile(r"<Privileged>\s*true\s*</Privileged>", re.IGNORECASE)


def path_is_command_module_bsl(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    return (
        low.endswith("/ext/commandmodule.bsl") or "/commands/" in low or "/commoncommands/" in low
    )


@functools.lru_cache(maxsize=32)
def config_root_for_file(path: str) -> str | None:
    try:
        p = Path(path).resolve()
    except OSError:
        p = Path(path)
    for parent in (p.parent, *p.parents):
        if (parent / "Configuration.xml").exists():
            return str(parent)
    return None


@functools.lru_cache(maxsize=8)
def crawl_config_cached(config_root: str) -> dict[str, Any]:
    objects = crawl_config(config_root)
    by_name: dict[str, Any] = {}
    for obj in objects:
        by_name[obj.name.casefold()] = obj
    return {"objects": objects, "by_name": by_name}


@functools.lru_cache(maxsize=256)
def read_text_cached(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def current_module_xml_context(path: str) -> dict[str, str]:
    low = path.replace("\\", "/")
    parts = Path(low).parts
    out: dict[str, str] = {}
    for idx, part in enumerate(parts):
        if part in FOLDER_TO_KIND:
            out["folder"] = part
            if idx + 1 < len(parts):
                out["object_name"] = parts[idx + 1]
            if "forms" in [p.casefold() for p in parts[idx + 1 :]]:
                try:
                    forms_idx = next(
                        i for i in range(idx + 1, len(parts)) if parts[i].casefold() == "forms"
                    )
                    if forms_idx + 1 < len(parts):
                        out["form_name"] = parts[forms_idx + 1]
                except StopIteration:
                    pass
            break
    return out


def current_object_xml_path(path: str) -> Path | None:
    root = config_root_for_file(path)
    if root is None:
        return None
    ctx = current_module_xml_context(path)
    folder = ctx.get("folder")
    object_name = ctx.get("object_name")
    if folder and object_name:
        return Path(root) / folder / f"{object_name}.xml"
    if "/commonmodules/" in path.replace("\\", "/").lower():
        mod_name = Path(path).parent.parent.name
        return Path(root) / "CommonModules" / f"{mod_name}.xml"
    return None


def current_form_xml_path(path: str) -> Path | None:
    root = config_root_for_file(path)
    if root is None:
        return None
    ctx = current_module_xml_context(path)
    folder = ctx.get("folder")
    object_name = ctx.get("object_name")
    form_name = ctx.get("form_name")
    if not (folder and object_name and form_name):
        return None
    return Path(root) / folder / object_name / "Forms" / form_name / "Ext" / "Form.xml"


@functools.lru_cache(maxsize=64)
def common_module_file_map(config_root: str) -> dict[str, dict[str, Any]]:
    root = Path(config_root) / "CommonModules"
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for xml_file in root.glob("*.xml"):
        name = xml_file.stem
        raw = read_text_cached(str(xml_file))
        module_file = root / name / "Ext" / "Module.bsl"
        proc_names: set[str] = set()
        if module_file.exists():
            snap = build_document_snapshot(
                str(module_file), content=read_text_cached(str(module_file))
            )
            proc_names = {proc.name.casefold() for proc in snap.procedures}
        result[name.casefold()] = {
            "name": name,
            "privileged": bool(_RE_XML_PRIVILEGED.search(raw)),
            "protected": bool(_RE_XML_PROTECTED.search(raw)),
            "proc_names": proc_names,
        }
    return result
