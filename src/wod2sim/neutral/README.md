# Neutral Analysis Surface

This subtree contains cross-cutting reporting and comparison utilities that are not
the simulator policy itself and not the WOD candidate stack itself.

Use it for:

- benchmark report generation
- benchmark-to-benchmark comparison
- AlpaSim metric normalization helpers

## Files

- `benchmark_reports.py` — report builders over benchmark outputs
- `benchmark_compare.py` — paired benchmark comparisons
- `alpasim_metrics.py` — metric import / normalization helpers for AlpaSim outputs

## Boundary

This is first-party analysis glue. It exists to keep reporting code out of:

- `src/wod2sim/simulator/`
- `src/wod2sim/model/`

If you are auditing core policy or benchmark behavior, start in those directories first
and return here only when you need report-generation logic.
