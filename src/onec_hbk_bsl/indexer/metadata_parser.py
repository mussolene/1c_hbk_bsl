"""
Parser for 1C configuration XML export (Выгрузка конфигурации в файлы).

Extracts object attributes (requisites), tabular sections, and form attributes/commands
from the standard Configurator XML export format.

Supported folders/kinds are listed in ``metadata_registry.FOLDER_TO_KIND`` (Designer XML
export), including registers, Web/HTTP services, constants, subsystems, roles, and more.

Returns lightweight dataclasses consumed by SymbolIndex.upsert_metadata().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from onec_hbk_bsl.indexer.discovery import iter_discovery_dirs
from onec_hbk_bsl.indexer.metadata_registry import (
    FOLDER_TO_KIND,
    xml_root_tags_for_kind,
)

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Public dataclasses
# -----------------------------------------------------------------------


@dataclass
class MetaMember:
    """A single member of a metadata object (attribute, TS, form attribute, command, etc.)."""

    name: str
    kind: (
        str  # 'attribute' | 'tabular_section' | 'form_attribute' | 'form_command' | 'ts_attribute'
    )
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


@dataclass
class MetadataAttribute:
    """XSD-like metadata attribute/requisite node."""

    name: str
    id: str = ""
    type_info: str = ""


@dataclass
class MetadataCommand:
    """XSD-like metadata command node."""

    name: str
    id: str = ""
    handler: str = ""


@dataclass
class MetadataEvent:
    """XSD-like metadata event binding node."""

    name: str
    id: str = ""
    handler: str = ""


@dataclass
class MetadataForm:
    """XSD-like form node with attributes, commands, and events."""

    name: str
    kind: str = ""
    uuid: str = ""
    attributes: list[MetadataAttribute] = field(default_factory=list)
    commands: list[MetadataCommand] = field(default_factory=list)
    events: list[MetadataEvent] = field(default_factory=list)


@dataclass
class MetadataObjectNode:
    """XSD-like metadata object node with nested table parts."""

    name: str
    type: str
    uuid: str = ""
    synonym_ru: str = ""
    file_path: str = ""
    attributes: list[MetadataAttribute] = field(default_factory=list)
    forms: list[MetadataForm] = field(default_factory=list)
    table_parts: list[MetadataObjectNode] = field(default_factory=list)

    def to_meta_object(self) -> MetaObject:
        """Return the legacy flat metadata projection used by SymbolIndex."""
        obj = MetaObject(
            name=self.name,
            kind=self.type,
            synonym_ru=self.synonym_ru,
            file_path=self.file_path,
        )
        for attr in self.attributes:
            obj.members.append(
                MetaMember(
                    name=attr.name,
                    kind="attribute",
                    parent_name=self.name,
                    parent_kind=self.type,
                    type_info=attr.type_info,
                )
            )
        for table_part in self.table_parts:
            obj.members.append(
                MetaMember(
                    name=table_part.name,
                    kind="tabular_section",
                    parent_name=self.name,
                    parent_kind=self.type,
                )
            )
            for attr in table_part.attributes:
                obj.members.append(
                    MetaMember(
                        name=f"{table_part.name}.{attr.name}",
                        kind="ts_attribute",
                        parent_name=self.name,
                        parent_kind=self.type,
                        type_info=attr.type_info,
                    )
                )
        for form in self.forms:
            for attr in form.attributes:
                obj.members.append(
                    MetaMember(
                        name=attr.name,
                        kind="form_attribute",
                        parent_name=self.name,
                        parent_kind=self.type,
                        type_info=f"Форма.{form.name}",
                    )
                )
            for command in form.commands:
                obj.members.append(
                    MetaMember(
                        name=command.name,
                        kind="form_command",
                        parent_name=self.name,
                        parent_kind=self.type,
                        type_info=f"Форма.{form.name}",
                    )
                )
        return obj


@dataclass
class MetadataConfigurationSnapshot:
    """XSD-like metadata configuration root object."""

    name: str = ""
    uuid: str = ""
    objects: list[MetadataObjectNode] = field(default_factory=list)

    def to_meta_objects(self) -> list[MetaObject]:
        """Return the legacy flat projection for existing index consumers."""
        return [obj.to_meta_object() for obj in self.objects]


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


def _find_first_descendant(elem: ET.Element, local_name: str) -> ET.Element | None:
    """Find the first descendant by local tag name."""
    for descendant in elem.iter():
        if descendant is elem:
            continue
        if _strip_ns(descendant.tag) == local_name:
            return descendant
    return None


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
        tree = ET.parse(str(xml_path))  # noqa: S314
        root = tree.getroot()
    except Exception as exc:
        logger.debug("Failed to parse %s: %s", xml_path, exc)
        return obj

    # Find the top-level object element (Catalog, Document, etc.)
    allowed_tags = xml_root_tags_for_kind(kind)
    obj_elem = None
    for child in root:
        tag_local = _strip_ns(child.tag)
        if tag_local in allowed_tags:
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
                obj.members.append(
                    MetaMember(
                        name=attr_name,
                        kind="attribute",
                        parent_name=object_name,
                        parent_kind=kind,
                        type_info=type_info,
                    )
                )

        elif local == "TabularSection":
            ts_name = _extract_attribute_name(child)
            if ts_name:
                obj.members.append(
                    MetaMember(
                        name=ts_name,
                        kind="tabular_section",
                        parent_name=object_name,
                        parent_kind=kind,
                    )
                )
                # Parse TS attributes
                ts_child_objects = _find_child(child, "ChildObjects")
                if ts_child_objects is not None:
                    for ts_child in ts_child_objects:
                        if _strip_ns(ts_child.tag) == "Attribute":
                            ts_attr_name = _extract_attribute_name(ts_child)
                            if ts_attr_name:
                                type_info = _extract_type_info(ts_child)
                                obj.members.append(
                                    MetaMember(
                                        name=f"{ts_name}.{ts_attr_name}",
                                        kind="ts_attribute",
                                        parent_name=object_name,
                                        parent_kind=kind,
                                        type_info=type_info,
                                    )
                                )

        elif local in ("Dimension", "Resource", "AccountingFlag", "ExtDimensionAccountingFlag"):
            # Register dimensions/resources
            attr_name = _extract_attribute_name(child)
            if attr_name:
                type_info = _extract_type_info(child)
                obj.members.append(
                    MetaMember(
                        name=attr_name,
                        kind="attribute",
                        parent_name=object_name,
                        parent_kind=kind,
                        type_info=type_info,
                    )
                )

        elif local == "EnumValue":
            enum_name = _extract_attribute_name(child)
            if enum_name:
                obj.members.append(
                    MetaMember(
                        name=enum_name,
                        kind="attribute",
                        parent_name=object_name,
                        parent_kind=kind,
                    )
                )

    return obj


def parse_metadata_object_xml(
    xml_path: str | Path, kind: str, object_name: str
) -> MetadataObjectNode:
    """
    Parse a 1C object XML file into an XSD-like metadata object node.

    This is the structured owner for configuration metadata. The legacy
    ``parse_object_xml`` API remains as a flat projection for SymbolIndex.
    """
    node = MetadataObjectNode(name=object_name, type=kind, file_path=str(xml_path))
    try:
        tree = ET.parse(str(xml_path))  # noqa: S314
        root = tree.getroot()
    except Exception as exc:
        logger.debug("Failed to parse %s: %s", xml_path, exc)
        return node

    obj_elem = _metadata_payload_element(root, kind)
    node.synonym_ru = _extract_synonym_ru(obj_elem)
    node.uuid = _extract_uuid(obj_elem)

    child_objects = _find_child(obj_elem, "ChildObjects")
    if child_objects is None:
        return node

    for child in child_objects:
        local = _strip_ns(child.tag)

        if local in (
            "Attribute",
            "Dimension",
            "Resource",
            "AccountingFlag",
            "ExtDimensionAccountingFlag",
            "EnumValue",
        ):
            attr = _metadata_attribute_from_xml(child)
            if attr is not None:
                node.attributes.append(attr)

        elif local == "TabularSection":
            table_part = _metadata_table_part_from_xml(child)
            if table_part is not None:
                node.table_parts.append(table_part)

    return node


def _metadata_payload_element(root: ET.Element, kind: str) -> ET.Element:
    """Return the actual metadata object element inside a Designer XML wrapper."""
    allowed_tags = xml_root_tags_for_kind(kind)
    for child in root:
        if _strip_ns(child.tag) in allowed_tags:
            return child
    return root


def _metadata_attribute_from_xml(elem: ET.Element) -> MetadataAttribute | None:
    name = _extract_attribute_name(elem)
    if not name:
        return None
    return MetadataAttribute(
        name=name,
        id=_extract_composite_id(elem),
        type_info=_extract_type_info(elem),
    )


def _metadata_table_part_from_xml(elem: ET.Element) -> MetadataObjectNode | None:
    name = _extract_attribute_name(elem)
    if not name:
        return None
    table_part = MetadataObjectNode(
        name=name,
        type="TablePart",
        uuid=_extract_uuid(elem),
    )
    child_objects = _find_child(elem, "ChildObjects")
    if child_objects is not None:
        for child in child_objects:
            if _strip_ns(child.tag) == "Attribute":
                attr = _metadata_attribute_from_xml(child)
                if attr is not None:
                    table_part.attributes.append(attr)
    return table_part


def _extract_synonym_ru(elem: ET.Element) -> str:
    props = _find_child(elem, "Properties")
    if props is None:
        return ""
    synonym_elem = _find_child(props, "Synonym")
    if synonym_elem is None:
        return ""
    for item in synonym_elem:
        lang_elem = _find_child(item, "lang")
        content_elem = _find_child(item, "content")
        if lang_elem is not None and (lang_elem.text or "").strip() == "ru":
            return (content_elem.text or "").strip() if content_elem is not None else ""
    return ""


def _extract_uuid(elem: ET.Element) -> str:
    for name in ("uuid", "id"):
        value = elem.get(name, "").strip()
        if value:
            return value
    props = _find_child(elem, "Properties")
    if props is not None:
        for name in ("UUID", "Uuid", "ID", "Id"):
            text = _find_child_text(props, name)
            if text:
                return text
    return ""


def _extract_composite_id(elem: ET.Element) -> str:
    props = _find_child(elem, "Properties")
    if props is None:
        return ""
    for name in ("ID", "Id", "UUID", "Uuid"):
        text = _find_child_text(props, name)
        if text:
            return text
    return ""


def _extract_attribute_name(elem: ET.Element) -> str:
    """Extract <Properties><Name> text from an Attribute/TabularSection element."""
    props = _find_child(elem, "Properties")
    if props is not None:
        name_elem = _find_child(props, "Name")
        if name_elem is not None:
            return (name_elem.text or "").strip()
    return ""


def _extract_type_info(elem: ET.Element) -> str:
    """Try to extract a readable type string from a <Properties><Type> element.

    Real Designer exports place value tokens as sibling <Type> children
    directly under <Properties><Type> (no <TypeDescription><Types> wrapper),
    e.g. <Type><v8:Type>cfg:CatalogRef.Организации</v8:Type></Type>. The
    <TypeDescription><Types> wrapper shape is also handled in case it occurs
    in other 1C artifacts this parser consumes.
    """
    props = _find_child(elem, "Properties")
    if props is None:
        return ""
    type_elem = _find_child(props, "Type")
    if type_elem is None:
        return ""
    td = _find_child(type_elem, "TypeDescription")
    types_elem = _find_child(td, "Types") if td is not None else None
    source = types_elem if types_elem is not None else type_elem
    tokens = [
        (child.text or "").strip()
        for child in source
        if _strip_ns(child.tag) == "Type" and (child.text or "").strip()
    ]
    return " ".join(tokens)[:120]


# -----------------------------------------------------------------------
# Form XML parser
# -----------------------------------------------------------------------


def parse_form_xml(
    xml_path: str | Path, object_name: str, object_kind: str, form_name: str
) -> list[MetaMember]:
    """
    Parse a 1C form XML file (Forms/FormName/Ext/Form.xml).

    Extracts:
    - Form attributes from <Attributes><Attribute name="...">
    - Form commands from <Commands><Command name="...">

    Returns a list of MetaMember instances.
    """
    members: list[MetaMember] = []
    try:
        tree = ET.parse(str(xml_path))  # noqa: S314
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
                    members.append(
                        MetaMember(
                            name=attr_name,
                            kind="form_attribute",
                            parent_name=object_name,
                            parent_kind=object_kind,
                            type_info=f"Форма.{form_name}",
                        )
                    )

    if commands_section is not None:
        for cmd in commands_section:
            if _strip_ns(cmd.tag) == "Command":
                cmd_name = cmd.get("name", "").strip()
                if cmd_name:
                    members.append(
                        MetaMember(
                            name=cmd_name,
                            kind="form_command",
                            parent_name=object_name,
                            parent_kind=object_kind,
                            type_info=f"Форма.{form_name}",
                        )
                    )

    return members


def parse_metadata_form_xml(
    xml_path: str | Path, object_name: str, object_kind: str, form_name: str
) -> MetadataForm:
    """
    Parse a form XML file into an XSD-like form node.

    ``object_name`` and ``object_kind`` are accepted for parity with
    ``parse_form_xml`` and future resolver use.
    """
    del object_name, object_kind
    form = MetadataForm(name=form_name)
    try:
        tree = ET.parse(str(xml_path))  # noqa: S314
        root = tree.getroot()
    except Exception as exc:
        logger.debug("Failed to parse form %s: %s", xml_path, exc)
        return form

    form.kind = root.get("type", "").strip() or root.get("kind", "").strip()
    form.uuid = root.get("uuid", "").strip()

    attrs_section = None
    commands_section = None
    events_section = None
    for child in root:
        local = _strip_ns(child.tag)
        if local == "Attributes":
            attrs_section = child
        elif local == "Commands":
            commands_section = child
        elif local == "Events":
            events_section = child

    if attrs_section is not None:
        for attr in attrs_section:
            if _strip_ns(attr.tag) == "Attribute":
                attr_name = attr.get("name", "").strip()
                if attr_name:
                    form.attributes.append(
                        MetadataAttribute(
                            name=attr_name,
                            id=attr.get("id", "").strip(),
                            type_info=_extract_form_attribute_type_info(attr),
                        )
                    )

    if commands_section is not None:
        for cmd in commands_section:
            if _strip_ns(cmd.tag) == "Command":
                cmd_name = cmd.get("name", "").strip()
                if cmd_name:
                    form.commands.append(
                        MetadataCommand(
                            name=cmd_name,
                            id=cmd.get("id", "").strip(),
                            handler=cmd.get("handler", "").strip(),
                        )
                    )

    if events_section is not None:
        for event in events_section:
            if _strip_ns(event.tag) == "Event":
                event_name = event.get("name", "").strip()
                if event_name:
                    form.events.append(
                        MetadataEvent(
                            name=event_name,
                            id=event.get("id", "").strip(),
                            handler=(event.text or event.get("handler", "")).strip(),
                        )
                    )

    return form


def _extract_form_attribute_type_info(attr: ET.Element) -> str:
    type_elem = _find_child(attr, "Type") or _find_first_descendant(attr, "Type")
    if type_elem is None:
        return ""
    text_parts = [
        (node.text or "").strip() for node in type_elem.iter() if (node.text or "").strip()
    ]
    return " ".join(text_parts)[:120]


# -----------------------------------------------------------------------
# Config root discovery and full crawl
# -----------------------------------------------------------------------


def find_config_root(workspace: str | Path, *, max_depth: int = 12) -> Path | None:
    """
    Search for a 1C configuration root directory within *workspace*.

    A config root is any directory containing a ``Configuration.xml`` file.
    Returns the first match found (breadth-first, up to *max_depth* levels deep).
    """
    workspace_path = Path(workspace)
    # Check workspace itself first
    if (workspace_path / "Configuration.xml").exists():
        return workspace_path

    queue: list[tuple[Path, int]] = [(workspace_path, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth > max_depth:
            continue
        for child in iter_discovery_dirs(current):
            if (child / "Configuration.xml").exists():
                return child
            queue.append((child, depth + 1))
    return None


def find_edt_configuration_marker(workspace: str | Path, *, max_depth: int = 14) -> Path | None:
    """
    Detect EDT project layout: ``.../Configuration/Configuration.mdo``.

    Our crawler targets Designer XML export (``Configuration.xml`` + type folders);
    EDT sources are not parsed here. This helper only *locates* an EDT marker for diagnostics.
    """
    workspace_path = Path(workspace)
    queue: list[tuple[Path, int]] = [(workspace_path, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth > max_depth:
            continue
        mdo = current / "Configuration" / "Configuration.mdo"
        if mdo.is_file():
            return mdo
        for child in iter_discovery_dirs(current):
            queue.append((child, depth + 1))
    return None


def iter_metadata_object_xmls(config_root: str | Path) -> list[tuple[Path, str, str]]:
    """Return object XML files as ``(xml_path, kind, object_name)`` tuples."""
    root = Path(config_root)
    result: list[tuple[Path, str, str]] = []
    for folder_name, kind in FOLDER_TO_KIND.items():
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for xml_file in sorted(folder.glob("*.xml")):
            result.append((xml_file, kind, xml_file.stem))
    return result


def iter_metadata_form_xmls(object_xml: str | Path) -> list[tuple[Path, str]]:
    """Return form XML files for one object XML as ``(form_xml, form_name)`` tuples."""
    xml_path = Path(object_xml)
    forms_dir = xml_path.with_suffix("") / "Forms"
    if not forms_dir.is_dir():
        return []
    result: list[tuple[Path, str]] = []
    for form_dir in sorted(forms_dir.iterdir()):
        if not form_dir.is_dir():
            continue
        form_xml = form_dir / "Ext" / "Form.xml"
        if form_xml.exists():
            result.append((form_xml, form_dir.name))
    return result


def iter_metadata_input_xmls(config_root: str | Path) -> list[Path]:
    """Return XML files that affect metadata indexing and fingerprinting."""
    root = Path(config_root)
    result = [root / "Configuration.xml"]
    for xml_file, _, _ in iter_metadata_object_xmls(root):
        result.append(xml_file)
        result.extend(form_xml for form_xml, _ in iter_metadata_form_xmls(xml_file))
    return result


def crawl_config(config_root: str | Path) -> list[MetaObject]:
    """
    Walk a 1C config export directory and parse all object XMLs + forms.

    Args:
        config_root: Path to the directory containing Configuration.xml.

    Returns:
        List of MetaObject instances with populated members.
    """
    snapshot = build_metadata_configuration_snapshot(config_root)
    objects = snapshot.to_meta_objects()

    logger.info(
        "Crawled config at %s: %d objects, %d total members",
        Path(config_root),
        len(objects),
        sum(len(o.members) for o in objects),
    )
    return objects


def build_metadata_configuration_snapshot(
    config_root: str | Path,
) -> MetadataConfigurationSnapshot:
    """
    Build an XSD-like metadata configuration root from a Designer XML export.

    The shape mirrors ``PlatformConfigStructure.xsd`` from the platform evidence
    layer while staying source-compatible with existing Designer XML inputs.
    """
    config_root = Path(config_root)
    snapshot = _parse_configuration_root(config_root / "Configuration.xml")

    for xml_file, kind, obj_name in iter_metadata_object_xmls(config_root):
        try:
            meta_obj = parse_metadata_object_xml(xml_file, kind, obj_name)
        except Exception as exc:
            logger.debug("Error parsing %s: %s", xml_file, exc)
            continue

        for form_xml, form_name in iter_metadata_form_xmls(xml_file):
            try:
                form = parse_metadata_form_xml(form_xml, obj_name, kind, form_name)
                meta_obj.forms.append(form)
            except Exception as exc:
                logger.debug("Error parsing form %s: %s", form_xml, exc)

        snapshot.objects.append(meta_obj)

    return snapshot


def _parse_configuration_root(path: Path) -> MetadataConfigurationSnapshot:
    snapshot = MetadataConfigurationSnapshot()
    if not path.is_file():
        return snapshot
    try:
        tree = ET.parse(str(path))  # noqa: S314
        root = tree.getroot()
    except Exception as exc:
        logger.debug("Failed to parse configuration root %s: %s", path, exc)
        return snapshot

    payload = root
    for child in root:
        if _strip_ns(child.tag) == "Configuration":
            payload = child
            break

    snapshot.name = _find_child_text(payload, "Name") or payload.get("name", "").strip()
    snapshot.uuid = _find_child_text(payload, "UUID") or payload.get("uuid", "").strip()
    properties = _find_child(payload, "Properties")
    if properties is not None:
        snapshot.name = snapshot.name or _find_child_text(properties, "Name")
        snapshot.uuid = snapshot.uuid or _find_child_text(properties, "UUID")
    return snapshot
