#!/usr/bin/env bash
# Run BSLLS vs onec-hbk-bsl parity helpers from the Cursor skill (format + diagnostics).
# JAR: BSLLS_JAR or .nosync/bsl-language-server/**/*.jar (see docs/BSLLS_BASELINE.md).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKS="${PARITY_CHECKS:-$ROOT/.cursor/skills/bsl-ast-mcp-skill/checks}"
REPORT="$ROOT/.nosync/reports"
STAMP="$(date +%Y%m%d-%H%M%S)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$REPORT"

if [[ ! -d "$CHECKS" ]]; then
  echo "run_bslls_parity: SKIP — нет каталога скриптов: $CHECKS" >&2
  echo "  (задайте PARITY_CHECKS=… к checks/ из bsl-ast-mcp-skill)" >&2
  exit 0
fi

echo "=== format_compare_bslls ($STAMP) ===" | tee "$REPORT/format_compare_bslls-$STAMP.log"
set +e
python3 "$CHECKS/format_compare_bslls.py" \
  --fixtures "$ROOT/tests/fixtures/format_parity" \
  2>&1 | tee -a "$REPORT/format_compare_bslls-$STAMP.log"
FMT_RC=${PIPESTATUS[0]}
set -e
echo "" | tee -a "$REPORT/format_compare_bslls-$STAMP.log"
echo "format_compare_bslls exit: $FMT_RC" | tee -a "$REPORT/format_compare_bslls-$STAMP.log"

echo "=== compare_diag_two_servers ($STAMP) ===" | tee "$REPORT/compare_diag_two_servers-$STAMP.log"
set +e
python3 "$CHECKS/compare_diag_two_servers.py" \
  "$ROOT/tests/fixtures/diag_baseline/sample.bsl" \
  "$ROOT/tests/fixtures/format_parity/sample_module.bsl" \
  "$ROOT/tests/fixtures/format_parity/procedure_export.bsl" \
  -o "$REPORT/compare_diag_two_servers-$STAMP.txt" \
  --summary-codes --stats \
  2>&1 | tee -a "$REPORT/compare_diag_two_servers-$STAMP.log"
DIAG_RC=${PIPESTATUS[0]}
set -e
echo "" | tee -a "$REPORT/compare_diag_two_servers-$STAMP.log"
echo "compare_diag_two_servers exit: $DIAG_RC" | tee -a "$REPORT/compare_diag_two_servers-$STAMP.log"
echo "Written: $REPORT/compare_diag_two_servers-$STAMP.txt" | tee -a "$REPORT/compare_diag_two_servers-$STAMP.log"
