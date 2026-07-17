# Baseline And Final Audit Report

This report records the command evidence for the neutral CVM release surface.
Commands were run from the repository root on 2026-07-17 with
`./.venv/bin/python` because bare `python` is not available on this shell PATH.
Temporary raw logs were written under `/tmp` and are not part of the public
artifact.

## Baseline And Quality Gates

| Command | Start UTC | End UTC | Duration | Exit | Result |
|---|---|---|---:|---:|---|
| `./.venv/bin/python -m ruff check .` | 2026-07-17T17:34:13Z | 2026-07-17T17:34:13Z | 0.107s | 0 | All checks passed. |
| `./.venv/bin/python -m build` | 2026-07-17T17:34:13Z | 2026-07-17T17:34:20Z | 7.283s | 0 | Built `wod2sim-0.1.0.tar.gz` and wheel. |
| `./.venv/bin/pre-commit run --all-files` | 2026-07-17T17:34:20Z | 2026-07-17T17:34:21Z | 0.691s | 1 | `ruff-format` would reformat 52 files. The broad formatting diff was not retained. |
| `./.venv/bin/python -m pytest -q` | 2026-07-17T17:34:21Z | 2026-07-17T17:34:23Z | 2.513s | 0 | 227 passed, 14 skipped, 15 subtests passed. |
| `make conformance PYTHON=./.venv/bin/python` | 2026-07-17T17:34:23Z | 2026-07-17T17:34:25Z | 1.810s | 0 | 227 passed, 14 skipped, 15 subtests passed. |
| `make demo PYTHON=./.venv/bin/python` | 2026-07-17T17:34:25Z | 2026-07-17T17:34:26Z | 0.230s | 0 | Synthetic demo valid; `valid_claim_evidence=false`. |

## Targeted Contract Tests

| Command | Start UTC | End UTC | Duration | Exit | Result |
|---|---|---|---:|---:|---|
| `./.venv/bin/python -m pytest -q tests -k "semantic or route"` | 2026-07-17T17:34:26Z | 2026-07-17T17:34:26Z | 0.601s | 0 | 9 passed, 232 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "temporal or resampl"` | 2026-07-17T17:34:26Z | 2026-07-17T17:34:27Z | 0.694s | 0 | 10 passed, 231 deselected, 15 subtests passed. |
| `./.venv/bin/python -m pytest -q tests -k "lifecycle or session"` | 2026-07-17T17:34:27Z | 2026-07-17T17:34:27Z | 0.546s | 0 | 10 passed, 231 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "plugin or entry_point"` | 2026-07-17T17:34:27Z | 2026-07-17T17:34:28Z | 1.032s | 0 | 5 passed, 236 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "deployment or readiness or launch"` | 2026-07-17T17:34:28Z | 2026-07-17T17:34:29Z | 0.687s | 0 | 20 passed, 221 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "evidence or audit or benchmark"` | 2026-07-17T17:34:29Z | 2026-07-17T17:34:30Z | 0.822s | 0 | 19 passed, 222 deselected. |
| `./.venv/bin/python -m pytest -q tests -k "fault"` | 2026-07-17T17:34:30Z | 2026-07-17T17:34:31Z | 0.635s | 0 | 5 passed, 236 deselected. |

## Release Commands

| Command | Exit | Result |
|---|---:|---|
| `make cvm-inventory PYTHON=./.venv/bin/python` | 0 | Refreshed ignored redacted environment/log snapshots under `artifacts/cvm`. |
| `make cvm-check PYTHON=./.venv/bin/python` | 0 | Ruff passed; conformance suite passed; paper validation passed. |
| `make cvm-demo PYTHON=./.venv/bin/python` | 0 | Synthetic demo artifact valid; `valid_claim_evidence=false`. |
| `make cvm-eval PYTHON=./.venv/bin/python` | 2 | Expected blocked-status exit: 36 completed core rows preserved, 18 direct-actor rows blocked by `direct_actor_oracle_proxy_missing`. |
| `make cvm-aggregate PYTHON=./.venv/bin/python` | 0 | Regenerated aggregate tables and figures from retained CVM results. |
| `make cvm-paper PYTHON=./.venv/bin/python` | 0 | Rebuilt 5-page root `wod2sim.pdf`. |
| `make cvm-validate PYTHON=./.venv/bin/python` | 0 | Submission validation passed. |

## Important Warnings

- `pre-commit run --all-files` is configured, but the `ruff-format` hook would
  reformat 52 existing files. That broad unrelated formatting diff was reverted
  and is not part of the release.
- `make cvm-eval` exits 2 because the configured core matrix still includes
  direct actor-aware rows without the required oracle actor proxy. This is a
  recorded precondition blocker, not a test failure.
- `pdfinfo`, `pdffonts`, `qpdf`, and `latexmk` are unavailable or not used by
  the current local validator; `mutool` and LaTeX log/source checks are used.
- Learned-policy tests remain skipped unless a legitimate local checkpoint is
  configured. No learned-policy result is claimed.

## Current Interpretation

The release status is complete with documented limitations for the CVM paper
draft. It supports dependency-light core integration evidence, semantic
route-boundary ablation evidence, false-block accounting for audit-valid rows,
and synthetic lifecycle/fault diagnostics. It does not support a policy-quality
benchmark, learned-policy result, direct-actor temporal ablation, or official
Waymo compatibility claim.
