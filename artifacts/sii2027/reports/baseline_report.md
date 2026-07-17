# SII 2027 Baseline Report

Captured: 2026-07-17T11:18Z UTC

Baseline policy: run the existing repository gates before SII functional or manuscript changes. Logs are stored under `artifacts/sii2027/logs/baseline/`.

## Command Results

| Command | Log | Exit | Duration | Result |
|---|---:|---:|---:|---|
| `./.venv/bin/python -m pytest -q` | `pytest_q.log` | 0 | 1 s | 188 passed, 14 skipped |
| `make conformance PYTHON=./.venv/bin/python` | `make_conformance.log` | 0 | 1 s | 188 passed, 14 skipped |
| `make demo PYTHON=./.venv/bin/python DEMO_OUTPUT=artifacts/sii2027/logs/baseline/demo-output` | `make_demo.log` | 0 | 0 s | synthetic public demo generated; benchmark claim false |
| `./.venv/bin/python -m ruff check .` | `ruff_check.log` | 0 | 0 s | all checks passed |
| `./.venv/bin/python -m build --outdir artifacts/sii2027/logs/baseline/build-dist` | `python_build.log` | 0 | 3 s | wheel and sdist built |
| `./.venv/bin/pre-commit run --all-files` | `precommit_all.log` | 1 | 4 s | `ruff` passed; `ruff-format` reformatted 43 existing files |
| `./.venv/bin/python -m pytest -q -rs` | `pytest_q_rs.log` | 0 | 1 s | explanatory rerun for skip reasons |

## Important Warnings And Interpretation

- `pre-commit run --all-files` is a baseline failure, not an SII implementation failure. The hook uses `ruff-format` and would reformat 43 existing tracked files. Those formatting edits were discarded to preserve the objective's rule against unrelated reformatting.
- The test suite skips 14 learned-policy tests because `torch` is not installed or the Torch environment is unavailable. This means the current environment validates dependency-light and adapter-contract paths, not learned-policy execution.
- `make demo` produced a valid synthetic contract artifact with `benchmark_claim=false` and `valid_claim_evidence=false`; it must not be presented as a closed-loop benchmark result.
- Full `pdfinfo`/`pdffonts`/`qpdf` validation is unavailable in this environment.
- The canonical `wod2sim.pdf` draft validates with local `mutool` and LaTeX/source fallback checks.

## Baseline Demo Evidence

Synthetic demo output:

- `artifacts/sii2027/logs/baseline/demo-output/demo-summary.json`
- `artifacts/sii2027/logs/baseline/demo-output/run-audit.json`
- `artifacts/sii2027/logs/baseline/demo-output/support-bundle-report.json`
- `artifacts/sii2027/logs/baseline/demo-output/aggregate/synthetic-contract-metrics.json`
- `artifacts/sii2027/logs/baseline/demo-output/aggregate/synthetic-contract-metrics.csv`

Observed synthetic-demo facts:

- Public assets only: true
- Benchmark claim: false
- Audit valid: true
- Audited frames: 8
- Route source counts: 8 `alpasim_waypoints`
- Support bundle valid: true
- Route-command lateral RMSE diagnostic: 1.312 m
- Road-center mean absolute lateral offset diagnostic: 4.508 m

These are synthetic contract diagnostics only. They are useful for artifact/schema validation, not for policy performance claims.

## Baseline Blockers

- Legacy `paper/paper.tex` remains as historical source and is no longer the
  top-level release paper target.
- SII-specific scripts, configs, paper directory, generated tables, generated figures, and Make targets now exist.
- The tracked canonical PDF is top-level `wod2sim.pdf`, built from
  `paper/sii2027/main.tex` with configured/blocked closed-loop claims and public
  synthetic diagnostics only.
- Real closed-loop experiment readiness is incomplete because the canonical `alpasim-base:latest` image is missing, AlpaSim worktrees are dirty, and learned-policy checkpoint/Torch availability is unverified.
- Gated USDZ scene assets exist locally but must remain referenced by identifiers/digests and never copied into public artifacts.
