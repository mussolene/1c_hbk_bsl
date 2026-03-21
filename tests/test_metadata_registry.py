"""Tests for unified metadata folder/kind/collection registry."""

from __future__ import annotations

from onec_hbk_bsl.indexer import metadata_registry as reg


def test_folder_to_kind_injective() -> None:
    kinds = list(reg.FOLDER_TO_KIND.values())
    assert len(kinds) == len(set(kinds)), "duplicate kind for different folders"


def test_kind_to_collection_covers_all_folders() -> None:
    for folder, kind in reg.FOLDER_TO_KIND.items():
        assert kind in reg.KIND_TO_COLLECTION, f"missing collection for {folder=} {kind=}"


def test_meta_collection_aliases_roundtrip() -> None:
    assert reg.META_COLLECTION_ALIASES["справочники"] == "Справочники"
    assert reg.META_COLLECTION_ALIASES["catalogs"] == "Справочники"
    assert reg.collection_for_alias("документы") == "Документы"


def test_defs_snapshot_len() -> None:
    snap = reg.defs_snapshot()
    assert len(snap) == len(reg.FOLDER_TO_KIND)
    assert all("folder" in row and "collection_ru" in row for row in snap)


def test_metadata_root_constants() -> None:
    assert reg.METADATA_ROOT_NAME_CF == reg.METADATA_ROOT_NAME.casefold()
