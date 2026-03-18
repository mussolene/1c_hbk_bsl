"""BSL indexer package — SQLite-backed symbol index with incremental git-diff updates."""

from bsl_analyzer.indexer.incremental import IncrementalIndexer
from bsl_analyzer.indexer.symbol_index import SymbolIndex

__all__ = ["SymbolIndex", "IncrementalIndexer"]
