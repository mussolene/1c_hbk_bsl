"""
pytest fixtures for bsl_analyzer tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bsl_analyzer.indexer.symbol_index import SymbolIndex

# Absolute path to the sample BSL fixture
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_BSL = FIXTURES_DIR / "sample.bsl"


@pytest.fixture
def sample_bsl_path() -> str:
    """Return the absolute path to the sample BSL fixture file."""
    return str(SAMPLE_BSL)


@pytest.fixture
def temp_workspace(tmp_path: Path) -> str:
    """
    Create a temporary workspace directory containing a copy of sample.bsl.

    Returns the absolute path of the workspace root.
    """
    bsl_dir = tmp_path / "src"
    bsl_dir.mkdir()
    shutil.copy(SAMPLE_BSL, bsl_dir / "sample.bsl")
    return str(tmp_path)


@pytest.fixture
def symbol_index(tmp_path: Path) -> SymbolIndex:
    """Return a fresh in-memory SymbolIndex for tests."""
    return SymbolIndex(db_path=":memory:")


@pytest.fixture
def populated_index(symbol_index: SymbolIndex, sample_bsl_path: str) -> SymbolIndex:
    """
    Return a SymbolIndex pre-populated with the symbols from sample.bsl.
    """
    from bsl_analyzer.analysis.call_graph import extract_calls
    from bsl_analyzer.analysis.symbols import extract_symbols
    from bsl_analyzer.parser.bsl_parser import BslParser

    parser = BslParser()
    tree = parser.parse_file(sample_bsl_path)
    symbols = extract_symbols(tree, file_path=sample_bsl_path)
    calls = extract_calls(tree, file_path=sample_bsl_path)

    sym_dicts = [
        {
            "name": s.name,
            "line": s.line,
            "character": s.character,
            "end_line": s.end_line,
            "end_character": s.end_character,
            "kind": s.kind,
            "is_export": s.is_export,
            "container": s.container,
            "signature": s.signature,
            "doc_comment": s.doc_comment,
        }
        for s in symbols
    ]
    call_dicts = [
        {
            "caller_line": c.caller_line,
            "caller_name": c.caller_name,
            "callee_name": c.callee_name,
            "callee_args_count": c.callee_args_count,
        }
        for c in calls
    ]
    symbol_index.upsert_file(sample_bsl_path, sym_dicts, call_dicts)
    return symbol_index
