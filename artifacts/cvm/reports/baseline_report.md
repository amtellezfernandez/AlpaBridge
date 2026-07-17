# Baseline And Final Audit Report

This report records the final audit commands run against the neutral CVM release
surface. Commands were executed from the repository root with
`PYTHON=./.venv/bin/python` unless otherwise stated.

| Command | Exit | Result |
|---|---:|---|
| `make cvm-inventory PYTHON=./.venv/bin/python` | 0 | Refreshed ignored redacted environment/log snapshots under `artifacts/cvm`. |
| `make cvm-check PYTHON=./.venv/bin/python` | 0 | Ruff passed; conformance suite passed with 226 passed, 14 skipped, 15 subtests passed; paper validation passed. |
| `make cvm-demo PYTHON=./.venv/bin/python` | 0 | Synthetic demo artifact valid; `valid_claim_evidence=false`. |
| `make cvm-eval PYTHON=./.venv/bin/python` | 2 | Expected blocked-status exit: 36 completed core rows preserved, 18 direct-actor rows blocked by `direct_actor_oracle_proxy_missing`. |
| `make cvm-aggregate PYTHON=./.venv/bin/python` | 0 | Regenerated aggregate tables and figures from retained CVM results. |
| `make cvm-paper PYTHON=./.venv/bin/python` | 0 | Rebuilt 5-page root `wod2sim.pdf`. |
| `make cvm-validate PYTHON=./.venv/bin/python` | 0 | Submission validation passed. |
| `./.venv/bin/python -m pytest -q` | 0 | Full suite passed with 227 passed, 14 skipped, 15 subtests passed. |

## Important Warnings

- `make cvm-eval` exits 2 because the configured core matrix still includes
  direct actor-aware rows without the required oracle actor proxy. This is a
  recorded precondition blocker, not a test failure.
- `pdfinfo`, `pdffonts`, `qpdf`, and `latexmk` are not required by the current
  local validator; `mutool` and LaTeX log/source checks are used instead.
- `python` is not on this shell PATH; the project interpreter is
  `./.venv/bin/python`.

## Current Interpretation

The release status is complete with documented limitations for the CVM paper
draft. It supports dependency-light core integration evidence, semantic
route-boundary ablation evidence, false-block accounting for audit-valid rows,
and synthetic lifecycle/fault diagnostics. It does not support a policy-quality
benchmark, learned-policy result, direct-actor temporal ablation, or official
Waymo compatibility claim.
