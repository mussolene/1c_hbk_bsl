# Diagnostic test migration map

A16 replaces `tests/test_diagnostics_extended.py` with execution-family modules.
Class and test names are unchanged. A former node id
`tests/test_diagnostics_extended.py::<Class>::<test>` now uses the family file below.

| Execution batch | New module | Pytest marker | Classes |
|---|---|---|---:|
| `01-core-snapshot-facts` | `tests/test_diagnostics_core_snapshot.py` | `integration` | 17 |
| `02-query-metadata-aggregation` | `tests/test_diagnostics_query_metadata.py` | `integration` | 8 |
| `03-method-procedure-contracts` | `tests/test_diagnostics_method_contracts.py` | `integration` | 16 |
| `04-common-module-context` | `tests/test_diagnostics_common_module.py` | `integration` | 1 |
| `05-heavy-process-typo-performance` | `tests/test_diagnostics_heavy.py` | `performance, slow` | 1 |
| `06-line-text-style-security` | `tests/test_diagnostics_line_text.py` | `unit` | 19 |
| `07-local-runtime-tail` | `tests/test_diagnostics_local_runtime.py` | `unit` | 52 |

Ambiguous multi-rule compatibility batches are assigned as follows:

- `TestAdditionalParityBatch` → `tests/test_diagnostics_local_runtime.py`
- `TestBsl036ComplexCondition` → `tests/test_diagnostics_core_snapshot.py`
- `TestBsl208Bsl256MixedScriptVsTypo` → `tests/test_diagnostics_heavy.py`
- `TestMethodAndStatementMessageParity` → `tests/test_diagnostics_method_contracts.py`
- `TestRuleMetadata` → `tests/test_diagnostics_local_runtime.py`
- `TestRuleMetadataCompleteness` → `tests/test_diagnostics_local_runtime.py`
- `TestRuleSelection` → `tests/test_diagnostics_local_runtime.py`
- `TestSecurityApiParityBatch` → `tests/test_diagnostics_line_text.py`
- `TestTailParityBatches` → `tests/test_diagnostics_query_metadata.py`

Baseline before migration: 114 classes, 803 test methods, semantic inventory SHA-256
`30253ffcdf941459f8cdacb19f56da1260663a780e0016ca88ec61c5ca332053`.
The inventory is the sorted `(class, test method, referenced BSL codes)` tuple set.
