# Baseline And Final Audit Report

This report records the command evidence for the neutral CVM release surface.
Commands were run from the repository root on 2026-07-17 with
`./.venv/bin/python` because bare `python` is not available on this shell PATH.
Temporary raw logs were written under `/tmp` and are not part of the public
package.

## Baseline And Quality Gates

| Command | Start UTC | End UTC | Duration | Exit | Result |
|---|---|---|---:|---:|---|
| `./.venv/bin/python -m ruff check .` | 2026-07-17T17:34:13Z | 2026-07-17T17:34:13Z | 0.107s | 0 | All checks passed. |
| `./.venv/bin/python -m build` | 2026-07-17T17:34:13Z | 2026-07-17T17:34:20Z | 7.283s | 0 | Built `wod2sim-0.1.0.tar.gz` and wheel. |
| `./.venv/bin/pre-commit run --all-files` | 2026-07-17T17:38:18Z | 2026-07-17T17:38:18Z | 0.325s | 0 | Ruff pre-commit hook passed without modifying files. |
| `./.venv/bin/python -m pytest -q` | 2026-07-17T18:52:54Z | 2026-07-17T18:52:58Z | 3.646s | 0 | 243 passed, 14 skipped, 15 subtests passed. |
| `make conformance PYTHON=./.venv/bin/python` | 2026-07-17T18:52:43Z | 2026-07-17T18:52:47Z | 3.417s | 0 | 243 passed, 14 skipped, 15 subtests passed. |
| `make demo PYTHON=./.venv/bin/python` | 2026-07-17T18:52:47Z | 2026-07-17T18:52:47Z | 0.252s | 0 | Synthetic demo valid; `valid_claim_evidence=false`. |

## Targeted Contract Tests

| Command | Start UTC | End UTC | Duration | Exit | Result |
|---|---|---|---:|---:|---|
| `./.venv/bin/python -m pytest -q tests -k "semantic or route"` | 2026-07-17T18:52:58Z | 2026-07-17T18:52:59Z | 0.783s | 0 | 10 passed, 247 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "temporal or resampl"` | 2026-07-17T18:52:59Z | 2026-07-17T18:53:00Z | 0.809s | 0 | 10 passed, 247 deselected, 15 subtests passed. |
| `./.venv/bin/python -m pytest -q tests -k "lifecycle or session"` | 2026-07-17T18:53:00Z | 2026-07-17T18:53:00Z | 0.775s | 0 | 10 passed, 247 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "plugin or entry_point"` | 2026-07-17T18:53:00Z | 2026-07-17T18:53:02Z | 1.368s | 0 | 5 passed, 252 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "deployment or readiness or launch"` | 2026-07-17T18:53:02Z | 2026-07-17T18:53:03Z | 1.424s | 0 | 20 passed, 237 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "evidence or audit or benchmark"` | 2026-07-17T18:53:03Z | 2026-07-17T18:53:04Z | 0.869s | 0 | 19 passed, 238 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "fault"` | 2026-07-17T18:53:04Z | 2026-07-17T18:53:05Z | 0.549s | 0 | 5 passed, 252 deselected. |

## Release Commands

| Command | Exit | Result |
|---|---:|---|
| `make cvm-inventory PYTHON=./.venv/bin/python` | 0 | Refreshed ignored redacted environment/log snapshots under `artifacts/cvm`. |
| `make cvm-check PYTHON=./.venv/bin/python` | 0 | Ruff passed; conformance suite passed with 243 passed, 14 skipped, and 15 subtests passed; paper validation passed. |
| `make cvm-demo PYTHON=./.venv/bin/python` | 0 | Synthetic demo artifact valid; `valid_claim_evidence=false`. |
| `make cvm-eval PYTHON=./.venv/bin/python` | 2 | Expected blocked-status exit: 36 completed core rows preserved, 18 direct-actor rows blocked by `direct_actor_oracle_proxy_missing`. |
| `make cvm-aggregate PYTHON=./.venv/bin/python` | 0 | Regenerated aggregate tables and figures from retained CVM results. |
| `make cvm-paper PYTHON=./.venv/bin/python` | 0 | Rebuilt 5-page root `wod2sim.pdf`. |
| `make cvm-validate PYTHON=./.venv/bin/python` | 0 | Submission validation passed. |
| `./.venv/bin/python scripts/validate_cvm_submission.py` | 0 | Submission validation passed, including abstract length, release metadata, and per-manifest `failure_attribution` consistency. |

## Important Warnings

- `make cvm-eval` exits 2 because the configured core matrix still includes
  direct actor-aware rows without the required oracle actor proxy. This is a
  recorded precondition blocker, not a test failure.
- `pdfinfo`, `pdffonts`, `qpdf`, and `latexmk` are unavailable or not used by
  the current local validator; `mutool` and LaTeX log/source checks are used.
- Learned-policy tests remain skipped unless a legitimate local checkpoint is
  configured. No learned-policy result is claimed.

## Current Interpretation

The release status is complete with documented limitations for the CVM paper
package. It supports dependency-light core integration evidence, semantic
route-boundary ablation evidence, false-block accounting for audit-valid rows,
and synthetic lifecycle/fault diagnostics. It does not support a policy-quality
benchmark, learned-policy result, direct-actor temporal ablation, or official
Waymo compatibility claim.

The validator now treats the integration-vs-policy boundary as a release gate:
blocked, failed, planned, and diagnostic rows cannot be labeled
policy-attributable unless the corresponding manifest is explicitly
claim-valid. The manifest rule must name semantic, temporal, lifecycle,
deployment, and evidence gates before policy behavior or policy failure can be
attributed to the integrated policy.
