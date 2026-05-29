from __future__ import annotations

import functools
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.document_snapshot import (
    find_procedure_names_from_tree,
    find_procedure_names_in_content,
)
from onec_hbk_bsl.indexer.metadata_parser import crawl_config
from onec_hbk_bsl.indexer.metadata_registry import FOLDER_TO_KIND
from onec_hbk_bsl.parser.bsl_parser import BslParser

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


@functools.lru_cache(maxsize=128)
def config_root_for_file(path: str) -> str | None:
    try:
        p = Path(path).resolve()
    except OSError:
        p = Path(path)
    for parent in (p.parent, *p.parents):
        if (parent / "Configuration.xml").exists():
            return str(parent)
    return None


@functools.lru_cache(maxsize=16)
def crawl_config_cached(config_root: str) -> dict[str, Any]:
    objects = crawl_config(config_root)
    by_name: dict[str, Any] = {}
    for obj in objects:
        by_name[obj.name.casefold()] = obj
    return {"objects": objects, "by_name": by_name}


@functools.lru_cache(maxsize=16)
def metadata_name_index_cached(config_root: str) -> frozenset[str]:
    root = Path(config_root)
    names: set[str] = set()
    for folder_name in FOLDER_TO_KIND:
        folder = root / folder_name
        if not folder.exists():
            continue
        for xml_file in folder.glob("*.xml"):
            names.add(xml_file.stem.casefold())
    return frozenset(names)


def _vcs_root_for_config(config_root: Path) -> Path:
    for parent in (config_root, *config_root.parents):
        if (parent / ".git").exists():
            return parent
    return config_root


@functools.lru_cache(maxsize=16)
def workspace_metadata_name_index_cached(config_root: str) -> frozenset[str]:
    root = Path(config_root).resolve()
    workspace_root = _vcs_root_for_config(root)
    config_roots = [path.parent for path in workspace_root.rglob("Configuration.xml")]
    if not config_roots:
        config_roots = [root]

    names: set[str] = set()
    for cfg_root in config_roots:
        names.update(metadata_name_index_cached(str(cfg_root)))
    return frozenset(names)


@functools.lru_cache(maxsize=4096)
def read_text_cached(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


@functools.lru_cache(maxsize=1024)
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


@functools.lru_cache(maxsize=128)
def common_module_file_map(config_root: str) -> dict[str, dict[str, Any]]:
    module_index = common_module_index_cached(config_root)
    result: dict[str, dict[str, Any]] = {}
    for name_cf, info in module_index.items():
        result[name_cf] = {
            "name": info["name"],
            "privileged": bool(info["privileged"]),
            "protected": bool(info["protected"]),
            "proc_names": common_module_proc_names_for_module_cached(config_root, name_cf),
        }
    return result


@functools.lru_cache(maxsize=128)
def common_module_index_cached(config_root: str) -> dict[str, dict[str, Any]]:
    root = Path(config_root) / "CommonModules"
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for xml_file in root.glob("*.xml"):
        name = xml_file.stem
        raw = read_text_cached(str(xml_file))
        module_file = root / name / "Ext" / "Module.bsl"
        result[name.casefold()] = {
            "name": name,
            "privileged": bool(_RE_XML_PRIVILEGED.search(raw)),
            "protected": bool(_RE_XML_PROTECTED.search(raw)),
            "module_file": str(module_file) if module_file.exists() else "",
        }
    return result


@functools.lru_cache(maxsize=128)
def common_module_privileged_map_cached(config_root: str) -> dict[str, dict[str, Any]]:
    module_index = common_module_index_cached(config_root)
    return {
        name_cf: {"name": info["name"], "privileged": bool(info["privileged"])}
        for name_cf, info in module_index.items()
    }


@functools.lru_cache(maxsize=4096)
def common_module_proc_names_for_file_cached(module_file: str) -> frozenset[str]:
    content = read_text_cached(module_file)
    if not content:
        return frozenset()
    tree = BslParser().parse_content(content, file_path=module_file)
    names = find_procedure_names_from_tree(tree)
    if names:
        return names
    return find_procedure_names_in_content(content)


@functools.lru_cache(maxsize=4096)
def common_module_proc_names_for_module_cached(
    config_root: str, module_name_cf: str
) -> frozenset[str]:
    info = common_module_index_cached(config_root).get(module_name_cf)
    if info is None:
        return frozenset()
    module_file = str(info.get("module_file") or "")
    if not module_file:
        return frozenset()
    return common_module_proc_names_for_file_cached(module_file)


@functools.lru_cache(maxsize=128)
def common_module_proc_names_map_cached(config_root: str) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    module_index = common_module_index_cached(config_root)
    for name_cf in module_index:
        result[name_cf] = common_module_proc_names_for_module_cached(config_root, name_cf)
    return result


@functools.lru_cache(maxsize=128)
def roles_with_new_objects_cached(config_root: str) -> tuple[str, ...]:
    roles_dir = Path(config_root) / "Roles"
    flagged: list[str] = []
    if not roles_dir.exists():
        return ()
    for xml_file in roles_dir.glob("*.xml"):
        role_name = xml_file.stem
        if role_name in {"FullAccess", "ПолныеПрава"}:
            continue
        text = read_text_cached(str(xml_file))
        match = _RE_XML_SET_FOR_NEW_OBJECTS.search(text)
        if match and match.group(1).lower() == "true":
            flagged.append(role_name)
    return tuple(flagged)


@functools.lru_cache(maxsize=32)
def config_has_protected_modules_cached(config_root: str) -> bool:
    root = Path(config_root)
    for xml_file in root.rglob("*.xml"):
        if xml_file.name in {"Configuration.xml", "ConfigDumpInfo.xml"}:
            continue
        if _RE_XML_PROTECTED.search(read_text_cached(str(xml_file))):
            return True
    return False


@functools.lru_cache(maxsize=128)
def event_subscription_handlers_by_module_cached(config_root: str) -> dict[str, tuple[str, ...]]:
    handlers: dict[str, list[str]] = defaultdict(list)
    subs_dir = Path(config_root) / "EventSubscriptions"
    if not subs_dir.exists():
        return {}
    for xml_file in subs_dir.glob("*.xml"):
        text = read_text_cached(str(xml_file))
        for match in _RE_XML_EVENT_HANDLER.finditer(text):
            handler = (match.group(1) or match.group(2) or "").strip()
            if "." not in handler:
                continue
            module_name, meth = handler.split(".", 1)
            if module_name and meth:
                handlers[module_name.casefold()].append(handler)
    return {module_name: tuple(values) for module_name, values in handlers.items()}


@functools.lru_cache(maxsize=128)
def scheduled_job_handlers_by_module_cached(
    config_root: str,
) -> dict[str, tuple[tuple[str, str], ...]]:
    handlers: dict[str, list[tuple[str, str]]] = defaultdict(list)
    jobs_dir = Path(config_root) / "ScheduledJobs"
    if not jobs_dir.exists():
        return {}
    prefix = "commonmodule."
    for xml_file in jobs_dir.glob("*.xml"):
        text = read_text_cached(str(xml_file))
        for match in _RE_XML_METHOD_NAME.finditer(text):
            handler = match.group(1).strip()
            handler_cf = handler.casefold()
            if not handler_cf.startswith(prefix):
                continue
            parts = handler.split(".", 2)
            if len(parts) != 3 or not parts[1] or not parts[2]:
                continue
            handlers[parts[1].casefold()].append((handler, xml_file.stem))
    return {module_name: tuple(values) for module_name, values in handlers.items()}
