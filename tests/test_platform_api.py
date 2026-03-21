"""
Tests for PlatformApi — 1C platform built-in type/function registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.platform_api import PlatformApi, get_platform_api

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api() -> PlatformApi:
    """Return a fresh PlatformApi instance with only built-in data."""
    return PlatformApi()


# ---------------------------------------------------------------------------
# Built-in global functions
# ---------------------------------------------------------------------------


class TestBuiltinGlobals:
    def test_find_global_russian(self, api: PlatformApi) -> None:
        result = api.find_global("Сообщить")
        assert result is not None
        assert "Сообщить" in result.name

    def test_find_global_case_insensitive(self, api: PlatformApi) -> None:
        result = api.find_global("сообщить")
        assert result is not None

    def test_find_global_english(self, api: PlatformApi) -> None:
        result = api.find_global("Message")
        assert result is not None

    def test_find_global_missing_returns_none(self, api: PlatformApi) -> None:
        assert api.find_global("НесуществующаяФункция") is None

    def test_global_completions_nonempty(self, api: PlatformApi) -> None:
        completions = api.get_global_completions()
        assert len(completions) > 10

    def test_global_completions_prefix_filter(self, api: PlatformApi) -> None:
        completions = api.get_global_completions("Сообщ")
        assert len(completions) >= 1
        assert all("Сообщ" in c["label"] or "сообщ" in c["label"].lower() for c in completions)

    def test_global_completion_fields(self, api: PlatformApi) -> None:
        completions = api.get_global_completions()
        item = completions[0]
        assert "label" in item
        assert "kind" in item
        assert item["kind"] == "function"


# ---------------------------------------------------------------------------
# Built-in types
# ---------------------------------------------------------------------------


class TestBuiltinTypes:
    def test_find_type_russian(self, api: PlatformApi) -> None:
        result = api.find_type("Запрос")
        assert result is not None
        assert result.name == "Запрос"

    def test_find_type_english(self, api: PlatformApi) -> None:
        result = api.find_type("Query")
        assert result is not None

    def test_find_type_case_insensitive(self, api: PlatformApi) -> None:
        result = api.find_type("запрос")
        assert result is not None

    def test_find_type_missing_returns_none(self, api: PlatformApi) -> None:
        assert api.find_type("НесуществующийТип") is None

    def test_type_has_methods(self, api: PlatformApi) -> None:
        t = api.find_type("Запрос")
        assert t is not None
        assert len(t.methods) > 0

    def test_type_has_properties(self, api: PlatformApi) -> None:
        t = api.find_type("Запрос")
        assert t is not None
        assert len(t.properties) > 0

    def test_method_completions_for_type(self, api: PlatformApi) -> None:
        completions = api.get_method_completions("Запрос")
        assert len(completions) > 0
        kinds = {c["kind"] for c in completions}
        assert "method" in kinds or "property" in kinds
        # completions use "label" key
        assert all("label" in c for c in completions)

    def test_method_completions_unknown_type(self, api: PlatformApi) -> None:
        completions = api.get_method_completions("НеизвестныйТип")
        assert completions == []

    def test_массив_type_exists(self, api: PlatformApi) -> None:
        assert api.find_type("Массив") is not None

    def test_структура_type_exists(self, api: PlatformApi) -> None:
        assert api.find_type("Структура") is not None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_returns_results(self, api: PlatformApi) -> None:
        results = api.search("Сообщить")
        assert len(results) >= 1

    def test_search_global_function(self, api: PlatformApi) -> None:
        results = api.search("Запрос")
        assert any("Запрос" in r["name"] for r in results)

    def test_search_limit(self, api: PlatformApi) -> None:
        results = api.search("а", limit=3)
        assert len(results) <= 3

    def test_search_empty_query(self, api: PlatformApi) -> None:
        # Empty query should return results (first N items)
        results = api.search("", limit=5)
        assert len(results) <= 5

    def test_search_result_has_fields(self, api: PlatformApi) -> None:
        results = api.search("Сообщить")
        if results:
            item = results[0]
            assert "name" in item
            assert "kind" in item


# ---------------------------------------------------------------------------
# JSON loading from data directory
# ---------------------------------------------------------------------------


class TestJsonLoading:
    def test_load_from_json_file(self, tmp_path: Path) -> None:
        """PlatformApi(data_dir=...) should merge JSON type definitions."""
        data_dir = tmp_path / "platform_api"
        data_dir.mkdir()
        type_def = {
            "name": "МойТип",
            "name_en": "MyType",
            "kind": "class",
            "description": "Тестовый тип",
            "methods": [
                {
                    "name": "МойМетод",
                    "name_en": "MyMethod",
                    "signature": "МойМетод() → Неопределено",
                    "description": "Тестовый метод",
                }
            ],
            "properties": [],
        }
        (data_dir / "my_type.json").write_text(json.dumps(type_def), encoding="utf-8")
        api = PlatformApi(data_dir=data_dir)

        result = api.find_type("МойТип")
        assert result is not None
        assert result.name == "МойТип"
        assert len(result.methods) == 1
        assert result.methods[0].name == "МойМетод"

    def test_load_invalid_json_ignored(self, tmp_path: Path) -> None:
        """Malformed JSON files should not crash the loader."""
        data_dir = tmp_path / "platform_api"
        data_dir.mkdir()
        (data_dir / "bad.json").write_text("{invalid json", encoding="utf-8")
        # Should not raise
        PlatformApi(data_dir=data_dir)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_platform_api_returns_instance(self) -> None:
        result = get_platform_api()
        assert result is not None
        assert isinstance(result, PlatformApi)

    def test_get_platform_api_singleton(self) -> None:
        a = get_platform_api()
        b = get_platform_api()
        assert a is b
