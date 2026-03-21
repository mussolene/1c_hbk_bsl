# Metadata folder / kind / collection registry

The single source of truth is [`src/onec_hbk_bsl/indexer/metadata_registry.py`](../src/onec_hbk_bsl/indexer/metadata_registry.py):

- **`FOLDER_TO_KIND`** — Designer XML export folder name → internal `kind` string.
- **`KIND_TO_COLLECTION`** — `kind` → Russian name of the global `Метаданные.<Коллекция>` property.
- **`META_COLLECTION_ALIASES`** — casefolded Russian + English folder aliases → canonical Russian collection name (used by LSP after `Справочники.` / `Catalogs.`).
- **`defs_snapshot()`** — list of `{folder, kind, collection_ru, has_metadata_manager}` for MCP and tooling.

## MCP contract

- **`bsl_meta_collection`** expects `collection` in canonical Russian (e.g. `Справочники`) or any alias known to `META_COLLECTION_ALIASES`.
- **`bsl_meta_index`** returns the indexer result plus **`metadata_kind_registry`**: the same data as `defs_snapshot()`.

## External references (local clones)

For comparison with other VS Code extensions (not vendored into this repo), clones under **`.nosync/`** (gitignored) may include:

- [lekot/VScodePluginFor1CDev](https://github.com/example/placeholder-vscode-metadata) — `src/utils/metadataTypeMapper.ts`, EDT vs Designer parsers.
- [asweetand-a11y/MetadataViewer1C](https://github.com/example/placeholder-metadata-viewer) — `src/ConfigurationFormats/edt.ts`, broad metadata coverage.

## EDT vs Designer export

- **Designer «выгрузка в файлы»**: `Configuration.xml` at the config root — fully supported by `crawl_config`.
- **EDT**: layout with `Configuration/Configuration.mdo` — detected by `find_edt_configuration_marker`; metadata crawl is skipped until a Designer XML export is available (`index_metadata` returns `reason: edt_layout_detected`).

## Lint rule BSL280

When the SQLite index contains metadata (`has_metadata()`), chains like `Справочники.ИмяОбъекта` and `Метаданные.Справочники.ИмяОбъекта` are checked: if `ИмяОбъекта` is missing from the indexed configuration, **BSL280** is reported. Comment lines (`//`) are skipped.
