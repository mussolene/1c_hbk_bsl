"""BSL analysis package — symbol extraction, call graph, and diagnostics."""

from bsl_analyzer.analysis.call_graph import build_call_graph, extract_calls
from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
from bsl_analyzer.analysis.symbols import extract_symbols

__all__ = ["extract_symbols", "extract_calls", "build_call_graph", "DiagnosticEngine"]
