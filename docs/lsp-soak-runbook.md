# LSP Soak Profiling (30-60 min)

Use this runbook to collect long-session drift evidence for memory, thread count, and diagnostic/runtime caches.

## Command

```bash
.venv/bin/python scripts/lsp_soak_profile.py \
  --workspace /abs/path/to/workspace \
  --duration-min 30 \
  --sample-interval-sec 15 \
  --file-limit 200 \
  --seed 42 \
  --index-workspace \
  --output-dir .tmp/reports/lsp-soak
```

For a longer run, set `--duration-min 60`.

## Outputs

- `lsp_soak_samples.jsonl`: timeline samples
- `lsp_soak_summary.json`: aggregate drift report

## Acceptance Hints

- `doc_cache_size` should return near baseline during steady-state (open/change/close cycle).
- `diag_timer_count` should stay low/stable in pull-diagnostics flow.
- `diag_cache_size` should remain bounded by active URI churn rather than monotonic growth.
- `threads` should stay stable (no runaway background growth).

## Notes

- `process_maxrss_mb` is OS-reported high-water mark and can grow monotonically even after memory is reclaimed.
- Use `python_heap_mb` and cache/thread counters as primary drift indicators for regression checks.
