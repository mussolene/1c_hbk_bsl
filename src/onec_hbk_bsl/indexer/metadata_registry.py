"""
Single source of truth for 1C configuration metadata folder/kind/collection mapping.

Used by metadata_parser (crawl), symbol_index (collection column), LSP completion
(_META_COLLECTIONS aliases), and MCP.

Folder names match the standard «Выгрузка конфигурации в файлы» (Designer XML) layout.
Russian collection names match global Метаданные.* managers in the 1C platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class MetadataKindDef:
    """One metadata type: Designer folder, internal kind id, platform collection name."""

    folder: str
    kind: str
    collection_ru: str
    # English / translit aliases for LSP (casefold keys built separately)
    en_aliases: tuple[str, ...] = ()
    # False if there is no Метаданные.<Collection> global access pattern (extremely rare)
    has_metadata_manager: bool = True


# Order: same logical groups as in 1C config tree (main objects first).
_METADATA_KIND_DEFS: tuple[MetadataKindDef, ...] = (
    MetadataKindDef("Catalogs", "Catalog", "Справочники", ("catalogs",)),
    MetadataKindDef("Documents", "Document", "Документы", ("documents",)),
    MetadataKindDef("DocumentJournals", "DocumentJournal", "ЖурналыДокументов", ("documentjournals",)),
    MetadataKindDef("Enums", "Enum", "Перечисления", ("enums",)),
    MetadataKindDef("Reports", "Report", "Отчеты", ("reports",)),
    MetadataKindDef("DataProcessors", "DataProcessor", "Обработки", ("dataprocessors",)),
    MetadataKindDef("ChartsOfCharacteristicTypes", "ChartOfCharacteristicTypes", "ПланыВидовХарактеристик", ("chartsofcharacteristictypes",)),
    MetadataKindDef("ChartsOfAccounts", "ChartOfAccounts", "ПланыСчетов", ("chartsofaccounts",)),
    MetadataKindDef("ChartsOfCalculationTypes", "ChartOfCalculationTypes", "ПланыВидовРасчета", ("chartsofcalculationtypes",)),
    MetadataKindDef("InformationRegisters", "InformationRegister", "РегистрыСведений", ("informationregisters",)),
    MetadataKindDef("AccumulationRegisters", "AccumulationRegister", "РегистрыНакопления", ("accumulationregisters",)),
    MetadataKindDef("AccountingRegisters", "AccountingRegister", "РегистрыБухгалтерии", ("accountingregisters",)),
    MetadataKindDef("CalculationRegisters", "CalculationRegister", "РегистрыРасчета", ("calculationregisters",)),
    MetadataKindDef("BusinessProcesses", "BusinessProcess", "БизнесПроцессы", ("businessprocesses",)),
    MetadataKindDef("Tasks", "Task", "Задачи", ("tasks",)),
    MetadataKindDef("ExchangePlans", "ExchangePlan", "ПланыОбмена", ("exchangeplans",)),
    MetadataKindDef("ExternalDataSources", "ExternalDataSource", "ВнешниеИсточникиДанных", ("externaldatasources",)),
    MetadataKindDef("Constants", "Constant", "Константы", ("constants",)),
    MetadataKindDef("CommonModules", "CommonModule", "ОбщиеМодули", ("commonmodules",)),
    MetadataKindDef("SessionParameters", "SessionParameter", "ПараметрыСеанса", ("sessionparameters",)),
    MetadataKindDef("FilterCriteria", "FilterCriterion", "КритерииОтбора", ("filtercriteria",)),
    MetadataKindDef("ScheduledJobs", "ScheduledJob", "РегламентныеЗадания", ("scheduledjobs",)),
    MetadataKindDef("FunctionalOptions", "FunctionalOption", "ФункциональныеОпции", ("functionaloptions",)),
    MetadataKindDef("FunctionalOptionsParameters", "FunctionalOptionsParameter", "ПараметрыФункциональныхОпций", ("functionaloptionsparameters",)),
    MetadataKindDef("SettingsStorages", "SettingsStorage", "ХранилищаНастроек", ("settingsstorages",)),
    MetadataKindDef("EventSubscriptions", "EventSubscription", "ПодпискиНаСобытия", ("eventsubscriptions",)),
    MetadataKindDef("CommandGroups", "CommandGroup", "ГруппыКоманд", ("commandgroups",)),
    MetadataKindDef("Roles", "Role", "Роли", ("roles",)),
    MetadataKindDef("Interfaces", "Interface", "Интерфейсы", ("interfaces",)),
    MetadataKindDef("Styles", "Style", "Стили", ("styles",)),
    MetadataKindDef("WebServices", "WebService", "WebСервисы", ("webservices",)),
    MetadataKindDef("HTTPServices", "HTTPService", "HTTPСервисы", ("httpservices",)),
    MetadataKindDef("WSReferences", "WSReference", "WSСсылки", ("wsreferences",)),
    MetadataKindDef("IntegrationServices", "IntegrationService", "СервисыИнтеграции", ("integrationservices",)),
    MetadataKindDef("Subsystems", "Subsystem", "Подсистемы", ("subsystems",)),
    MetadataKindDef("Sequences", "Sequence", "Последовательности", ("sequences",)),
    MetadataKindDef("DefinedTypes", "DefinedType", "ОпределяемыеТипы", ("definedtypes",)),
    MetadataKindDef("CommonForms", "CommonForm", "ОбщиеФормы", ("commonforms",)),
    MetadataKindDef("CommonTemplates", "CommonTemplate", "ОбщиеМакеты", ("commontemplates",)),
    MetadataKindDef("CommonPictures", "CommonPicture", "ОбщиеКартинки", ("commonpictures",)),
)

FOLDER_TO_KIND: Final[dict[str, str]] = {d.folder: d.kind for d in _METADATA_KIND_DEFS}

KIND_TO_COLLECTION: Final[dict[str, str]] = {
    d.kind: d.collection_ru for d in _METADATA_KIND_DEFS if d.has_metadata_manager
}

# RU/EN alias (casefold) -> canonical Russian collection name for LSP after «Collection.».
META_COLLECTION_ALIASES: Final[dict[str, str]] = {}
for d in _METADATA_KIND_DEFS:
    if not d.has_metadata_manager:
        continue
    ru_cf = d.collection_ru.casefold()
    META_COLLECTION_ALIASES[ru_cf] = d.collection_ru
    META_COLLECTION_ALIASES[d.folder.casefold()] = d.collection_ru
    for a in d.en_aliases:
        META_COLLECTION_ALIASES[a.casefold()] = d.collection_ru

# «Метаданные» is not a collection; handled specially in LSP.
METADATA_ROOT_NAME: Final[str] = "Метаданные"
METADATA_ROOT_NAME_CF: Final[str] = METADATA_ROOT_NAME.casefold()

# All canonical Russian collection names (for Метаданные. completion).
ALL_COLLECTION_NAMES_RU: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(d.collection_ru for d in _METADATA_KIND_DEFS if d.has_metadata_manager)
)

# Kinds we index from Designer XML (for tests / diagnostics).
ALL_KINDS: Final[frozenset[str]] = frozenset(d.kind for d in _METADATA_KIND_DEFS)

def xml_root_tags_for_kind(kind: str) -> frozenset[str]:
    """Local XML element names that may represent the root of an object of *kind*."""
    return frozenset({kind})


def collection_for_alias(token_cf: str) -> str | None:
    """Resolve a casefolded identifier to canonical Russian collection name, or None."""
    return META_COLLECTION_ALIASES.get(token_cf)


def defs_snapshot() -> list[dict[str, str | bool]]:
    """Machine-readable list for MCP / docs (folder, kind, collection_ru)."""
    return [
        {
            "folder": d.folder,
            "kind": d.kind,
            "collection_ru": d.collection_ru,
            "has_metadata_manager": d.has_metadata_manager,
        }
        for d in _METADATA_KIND_DEFS
    ]
