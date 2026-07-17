# Reproducing Current SII 2027 Artifacts

Current status: buildable SII draft with documented blocked closed-loop results and
public synthetic lifecycle/fault diagnostics.

## Baseline Inventory

```bash
make sii2027-inventory
```

## Existing Quality Gates

```bash
./.venv/bin/python -m pytest -q
make conformance PYTHON=./.venv/bin/python
make demo PYTHON=./.venv/bin/python DEMO_OUTPUT=artifacts/sii2027/logs/baseline/demo-output
./.venv/bin/python -m ruff check .
./.venv/bin/python -m build --outdir artifacts/sii2027/logs/baseline/build-dist
```

`pre-commit run --all-files` currently fails because `ruff-format` would reformat unrelated
tracked files. The formatting changes should not be accepted as part of the SII paper work.

## Matrix Expansion

```bash
./.venv/bin/python scripts/run_sii2027_matrix.py \
  --config configs/sii2027/core.yaml \
  --output artifacts/sii2027/results/core \
  --resume
```

The command currently records blocked rows unless `--execute` is implemented and all runtime
preconditions are satisfied.

## Public Synthetic Diagnostics

```bash
make sii2027-synthetic PYTHON=./.venv/bin/python
```

This executes the public synthetic lifecycle and fault-injection matrices. These rows are
diagnostic service-harness evidence only; they are not claim-valid closed-loop scene rollouts.

## Aggregate And Figures

```bash
./.venv/bin/python scripts/aggregate_sii2027.py \
  --inputs artifacts/sii2027/results \
  --output artifacts/sii2027/results

./.venv/bin/python scripts/generate_sii2027_figures.py \
  --summary artifacts/sii2027/results/summary.json \
  --runs artifacts/sii2027/results/runs.csv \
  --output artifacts/sii2027
```

## Paper Build

```bash
make sii2027-paper
```

The output PDF is the repository-root `wod2sim.pdf`. The `paper/sii2027/`
directory contains the source and generated TeX inputs, not a second tracked
paper PDF.

## Paper Validation

```bash
make sii2027-validate
```

The validator uses `mutool` and LaTeX/source checks because `pdfinfo`, `pdffonts`, and
`qpdf` are not available in the current environment.

## Current Claim Boundary

- Configured rows: 145
- Attempted rows: 55
- Completed rows: 55
- Blocked rows: 90
- Claim-valid rows: 0

Do not cite the current aggregate as a closed-loop result. Synthetic diagnostics may be
cited only as synthetic diagnostics.
