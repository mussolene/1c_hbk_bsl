"""
Parser for 1C configuration XML export (Выгрузка конфигурации в файлы).

Extracts object attributes (requisites), tabular sections, and form attributes/commands
from the standard Configurator XML export format.

Supported object types: Catalog, Document, DataProcessor, InformationRegister,
AccumulationRegister, AccountingRegister, ExchangePlan, BusinessProcess, Task,
ChartOfAccounts, ChartOfCalculationTypes, ChartOfCharacteristicTypes,
Enum, CommonModule, Report, Subsystem.

Returns lightweight dataclasses consumed by SymbolIndex.upsert_metadata().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Public dataclasses
# -----------------------------------------------------------------------

# 1C object type folder names → canonical kind
_FOLDER_TO_KIND: dict[str, str] = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "DataProcessors": "DataProcessor",
    "Reports": "Report",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "ExchangePlans": "ExchangePlan",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "Enums": "Enum",
    "CommonModules": "CommonModule",
    "Subsystems": "Subsystem",
    "Constants": "Constant",
    "Sequences": "Sequence",
    "DefinedTypes": "DefinedType",
}

# Global 1C manager collections — available as `Справочники.НазваниеОбъекта`
_KIND_TO_COLLECTION: dict[str, str] = {
    "Catalog": "Справочники",
    "Document": "Документы",
    "DataProcessor": "Обработки",
    "Report": "Отчеты",
    "InformationRegister": "РегистрыСведений",
    "AccumulationRegister": "РегистрыНакопления",
    "AccountingRegister": "РегистрыБухгалтерии",
    "CalculationRegister": "РегистрыРасчета",
    "ExchangePlan": "ПланыОбмена",
    "BusinessProcess": "БизнесПроцессы",
    "Task": "Задачи",
    "ChartOfAccounts": "ПланыСчетов",
    "ChartOfCalculationTypes": "ПланыВидовРасчета",
    "ChartOfCharacteristicTypes": "ПланыВидовХарактеристик",
    "Enum": "Перечисления",
    "CommonModule": "ОбщиеМодули",
}


@dataclass
class MetaMember:
    """A single member of a metadata object (attribute, TS, form attribute, command, etc.)."""

    name: str
    kind: str  # 'attribute' | 'tabular_section' | 'form_attribute' | 'form_command' | 'ts_attribute'
    parent_name: str  # object name (e.g. 'Контрагенты')
    parent_kind: str  # object kind (e.g. 'Catalog')
    type_info: str = ""  # human-readable type string if available
    synonym_ru: str = ""  # Russian synonym for display


@dataclass
class MetaObject:
    """A single 1C configuration object with its members."""

    name: str
    kind: str  # 'Catalog' | 'Document' | etc.
    synonym_ru: str = ""
    file_path: str = ""
    members: list[MetaMember] = field(default_factory=list)


# -----------------------------------------------------------------------
# Namespace helpers
# -----------------------------------------------------------------------

def _strip_ns(tag: str) -> str:
    """Remove XML namespace from tag name: '{ns}LocalName' → 'LocalName'."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_child_text(elem: ET.Element, local_name: str) -> str:
    """Find direct child by local tag name and return its text (stripped), or ''."""
    for child in elem:
        if _strip_ns(child.tag) == local_name:
            return (child.text or "").strip()
    return ""


def _find_child(elem: ET.Element, local_name: str) -> ET.Element | None:
    """Find first direct child by local tag name."""
    for child in elem:
        if _strip_ns(child.tag) == local_name:
            return child
    return None


def _find_descendant(elem: ET.Element, *path: str) -> ET.Element | None:
    """Walk a sequence of local tag names to find a nested element."""
    current = elem
    for name in path:
        current = _find_child(current, name)
        if current is None:
            return None
    return current


# -----------------------------------------------------------------------
# Object XML parser
# -----------------------------------------------------------------------

def parse_object_xml(xml_path: str | Path, kind: str, object_name: str) -> MetaObject:
    """
    Parse a 1C object XML file (e.g. Catalogs/Контрагенты.xml).

    Extracts:
    - Object synonym (Russian)
    - Attributes (requisites) from ChildObjects > Attribute > Properties > Name
    - Tabular sections from ChildObjects > TabularSection
    - TS attributes from TabularSection > ChildObjects > Attribute > Properties > Name

    Args:
        xml_path: Path to the object XML file.
        kind: Canonical kind string (e.g. 'Catalog').
        object_name: Technical name of the object.

    Returns:
        MetaObject with populated members.
    """
    obj = MetaObject(name=object_name, kind=kind, file_path=str(xml_path))
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception as exc:
        logger.debug("Failed to parse %s: %s", xml_path, exc)
        return obj

    # Find the top-level object element (Catalog, Document, etc.)
    obj_elem = None
    for child in root:
        tag_local = _strip_ns(child.tag)
        if tag_local in (kind, "Catalog", "Document", "DataProcessor", "InformationRegister",
                         "AccumulationRegister", "AccountingRegister", "ExchangePlan",
                         "BusinessProcess", "Task", "ChartOfAccounts", "ChartOfCalculationTypes",
                         "ChartOfCharacteristicTypes", "Enum", "Report", "Sequence",
                         "CalculationRegister", "CommonModule", "Subsystem", "Constant"):
            obj_elem = child
            break

    if obj_elem is None:
        # Some formats wrap differently — use root
        obj_elem = root

    # Extract synonym
    props = _find_child(obj_elem, "Properties")
    if props is not None:
        synonym_elem = _find_child(props, "Synonym")
        if synonym_elem is not None:
            # <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>...</v8:content></v8:item></Synonym>
            for item in synonym_elem:
                lang_elem = _find_child(item, "lang")
                content_elem = _find_child(item, "content")
                if lang_elem is not None and (lang_elem.text or "").strip() == "ru":
                    if content_elem is not None:
                        obj.synonym_ru = (content_elem.text or "").strip()
                    break

    # Find ChildObjects section
    child_objects = _find_child(obj_elem, "ChildObjects")
    if child_objects is None:
        return obj

    for child in child_objects:
        local = _strip_ns(child.tag)

        if local == "Attribute":
            # Requisite attribute
            attr_name = _extract_attribute_name(child)
            if attr_name:
                type_info = _extract_type_info(child)
                obj.members.append(MetaMember(
                    name=attr_name,
                    kind="attribute",
                    parent_name=object_name,
                    parent_kind=kind,
                    type_info=type_info,
                ))

        elif local == "TabularSection":
            ts_name = _extract_attribute_name(child)
            if ts_name:
                obj.members.append(MetaMember(
                    name=ts_name,
                    kind="tabular_section",
                    parent_name=object_name,
                    parent_kind=kind,
                ))
                # Parse TS attributes
                ts_child_objects = _find_child(child, "ChildObjects")
                if ts_child_objects is not None:
                    for ts_child in ts_child_objects:
                        if _strip_ns(ts_child.tag) == "Attribute":
                            ts_attr_name = _extract_attribute_name(ts_child)
                            if ts_attr_name:
                                type_info = _extract_type_info(ts_child)
                                obj.members.append(MetaMember(
                                    name=f"{ts_name}.{ts_attr_name}",
                                    kind="ts_attribute",
                                    parent_name=object_name,
                                    parent_kind=kind,
                                    type_info=type_info,
                                ))

        elif local in ("Dimension", "Resource", "AccountingFlag", "ExtDimensionAccountingFlag"):
            # Register dimensions/resources
            attr_name = _extract_attribute_name(child)
            if attr_name:
                type_info = _extract_type_info(child)
                obj.members.append(MetaMember(
                    name=attr_name,
                    kind="attribute",
                    parent_name=object_name,
                    parent_kind=kind,
                    type_info=type_info,
                ))

        elif local == "EnumValue":
            enum_name = _extract_attribute_name(child)
            if enum_name:
                obj.members.append(MetaMember(
                    name=enum_name,
                    kind="attribute",
                    parent_name=object_name,
                    parent_kind=kind,
                ))

    return obj


def _extract_attribute_name(elem: ET.Element) -> str:
    """Extract <Properties><Name> text from an Attribute/TabularSection element."""
    props = _find_child(elem, "Properties")
    if props is not None:
        name_elem = _find_child(props, "Name")
        if name_elem is not None:
            return (name_elem.text or "").strip()
    return ""


def _extract_type_info(elem: ET.Element) -> str:
    """Try to extract a readable type string from Type > TypeDescription."""
    props = _find_child(elem, "Properties")
    if props is None:
        return ""
    type_elem = _find_child(props, "Type")
    if type_elem is None:
        return ""
    # <TypeDescription><Types>...</Types></TypeDescription>
    td = _find_child(type_elem, "TypeDescription")
    if td is None:
        td = type_elem
    types_elem = _find_child(td, "Types")
    if types_elem is not None:
        types_text = " ".join(
            (t.text or "").strip() for t in types_elem if (t.text or "").strip()
        )
        return types_text[:120]
    return ""


# -----------------------------------------------------------------------
# Form XML parser
# -----------------------------------------------------------------------

def parse_form_xml(xml_path: str | Path, object_name: str, object_kind: str,
                   form_name: str) -> list[MetaMember]:
    """
    Parse a 1C form XML file (Forms/FormName/Ext/Form.xml).

    Extracts:
    - Form attributes from <Attributes><Attribute name="...">
    - Form commands from <Commands><Command name="...">

    Returns a list of MetaMember instances.
    """
    members: list[MetaMember] = []
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception as exc:
        logger.debug("Failed to parse form %s: %s", xml_path, exc)
        return members

    # <Attributes>
    attrs_section = None
    commands_section = None
    for child in root:
        local = _strip_ns(child.tag)
        if local == "Attributes":
            attrs_section = child
        elif local == "Commands":
            commands_section = child

    if attrs_section is not None:
        for attr in attrs_section:
            if _strip_ns(attr.tag) == "Attribute":
                attr_name = attr.get("name", "").strip()
                if attr_name:
                    members.append(MetaMember(
                        name=attr_name,
                        kind="form_attribute",
                        parent_name=object_name,
                        parent_kind=object_kind,
                        type_info=f"Форма.{form_name}",
                    ))

    if commands_section is not None:
        for cmd in commands_section:
            if _strip_ns(cmd.tag) == "Command":
                cmd_name = cmd.get("name", "").strip()
                if cmd_name:
                    members.append(MetaMember(
                        name=cmd_name,
                        kind="form_command",
                        parent_name=object_name,
                        parent_kind=object_kind,
                        type_info=f"Форма.{form_name}",
                    ))

    return members


# -----------------------------------------------------------------------
# Config root discovery and full crawl
# -----------------------------------------------------------------------

def find_config_root(workspace: str | Path) -> Path | None:
    """
    Search for a 1C configuration root directory within *workspace*.

    A config root is any directory containing a ``Configuration.xml`` file.
    Returns the first match found (breadth-first, up to 5 levels deep).
    """
    workspace_path = Path(workspace)
    # Check workspace itself first
    if (workspace_path / "Configuration.xml").exists():
        return workspace_path

    # BFS up to depth 5
    queue: list[tuple[Path, int]] = [(workspace_path, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth > 5:
            continue
        try:
            for child in current.iterdir():
                if child.is_dir():
                    if (child / "Configuration.xml").exists():
                        return child
                    queue.append((child, depth + 1))
        except PermissionError:
            continue
    return None


def crawl_config(config_root: str | Path) -> list[MetaObject]:
    """
    Walk a 1C config export directory and parse all object XMLs + forms.

    Args:
        config_root: Path to the directory containing Configuration.xml.

    Returns:
        List of MetaObject instances with populated members.
    """
    config_root = Path(config_root)
    objects: list[MetaObject] = []

    for folder_name, kind in _FOLDER_TO_KIND.items():
        folder = config_root / folder_name
        if not folder.exists():
            continue

        # Each object is represented by Name.xml + optional Name/ subdir
        for xml_file in sorted(folder.glob("*.xml")):
            obj_name = xml_file.stem
            try:
                meta_obj = parse_object_xml(xml_file, kind, obj_name)
            except Exception as exc:
                logger.debug("Error parsing %s: %s", xml_file, exc)
                continue

            # Parse forms from Name/Forms/FormName/Ext/Form.xml
            obj_dir = folder / obj_name
            forms_dir = obj_dir / "Forms" if obj_dir.is_dir() else None
            if forms_dir and forms_dir.is_dir():
                for form_dir in sorted(forms_dir.iterdir()):
                    if not form_dir.is_dir():
                        continue
                    form_xml = form_dir / "Ext" / "Form.xml"
                    if form_xml.exists():
                        try:
                            form_members = parse_form_xml(
                                form_xml, obj_name, kind, form_dir.name
                            )
                            meta_obj.members.extend(form_members)
                        except Exception as exc:
                            logger.debug("Error parsing form %s: %s", form_xml, exc)

            objects.append(meta_obj)

    logger.info(
        "Crawled config at %s: %d objects, %d total members",
        config_root,
        len(objects),
        sum(len(o.members) for o in objects),
    )
    return objects
