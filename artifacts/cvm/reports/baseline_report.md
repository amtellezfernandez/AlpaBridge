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
| `./.venv/bin/python -m pytest -q` | 2026-07-17T18:52:54Z | 2026-07-17T18:52:58Z | 3.646s | 0 | 247 passed, 14 skipped, 15 subtests passed after release-validator hardening. |
| `make conformance PYTHON=./.venv/bin/python` | 2026-07-17T18:52:43Z | 2026-07-17T18:52:47Z | 3.417s | 0 | 247 passed, 14 skipped, 15 subtests passed after release-validator hardening. |
| `make demo PYTHON=./.venv/bin/python` | 2026-07-17T18:52:47Z | 2026-07-17T18:52:47Z | 0.252s | 0 | Synthetic demo valid; `valid_claim_evidence=false`. |

## Targeted Contract Tests

| Command | Start UTC | End UTC | Duration | Exit | Result |
|---|---|---|---:|---:|---|
| `./.venv/bin/python -m pytest -q tests -k "semantic or route"` | 2026-07-17T18:52:58Z | 2026-07-17T18:52:59Z | 0.783s | 0 | 10 passed, 251 deselected after release-validator hardening. |
| `./.venv/bin/python -m pytest -q tests -k "temporal or resampl"` | 2026-07-17T18:52:59Z | 2026-07-17T18:53:00Z | 0.809s | 0 | 10 passed, 251 deselected, 15 subtests passed after release-validator hardening. |
| `./.venv/bin/python -m pytest -q tests -k "lifecycle or session"` | 2026-07-17T18:53:00Z | 2026-07-17T18:53:00Z | 0.775s | 0 | 10 passed, 251 deselected after release-validator hardening. |
| `./.venv/bin/python -m pytest -q tests -k "plugin or entry_point"` | 2026-07-17T18:53:00Z | 2026-07-17T18:53:02Z | 1.368s | 0 | 5 passed, 256 deselected after release-validator hardening. |
| `./.venv/bin/python -m pytest -q tests -k "deployment or readiness or launch"` | 2026-07-17T18:53:02Z | 2026-07-17T18:53:03Z | 1.424s | 0 | 20 passed, 241 deselected after release-validator hardening. |
| `./.venv/bin/python -m pytest -q tests -k "evidence or audit or benchmark"` | 2026-07-17T18:53:03Z | 2026-07-17T18:53:04Z | 0.869s | 0 | 19 passed, 242 deselected after release-validator hardening. |
| `./.venv/bin/python -m pytest -q tests -k "fault"` | 2026-07-17T18:53:04Z | 2026-07-17T18:53:05Z | 0.549s | 0 | 5 passed, 256 deselected after release-validator hardening. |

## Release Commands

| Command | Exit | Result |
|---|---:|---|
| `make cvm-inventory PYTHON=./.venv/bin/python` | 0 | Refreshed ignored redacted environment/log snapshots under `artifacts/cvm`. |
| `make cvm-check PYTHON=./.venv/bin/python` | 0 | Ruff passed; conformance suite passed with 255 passed, 14 skipped, and 15 subtests passed after metadata, PDF font, source-layout, and LaTeX-log validation hardening; paper validation passed. |
| `make cvm-demo PYTHON=./.venv/bin/python` | 0 | Synthetic demo artifact valid; `valid_claim_evidence=false`. |
| `make cvm-eval PYTHON=./.venv/bin/python` | 2 | Expected blocked-status exit: 36 completed core rows preserved, 18 direct-actor rows blocked by `direct_actor_oracle_proxy_missing`. |
| `make cvm-aggregate PYTHON=./.venv/bin/python` | 0 | Regenerated aggregate tables and figures from retained CVM results. |
| `make cvm-paper PYTHON=./.venv/bin/python` | 0 | Rebuilt 5-page root `wod2sim.pdf`. |
| `make cvm-validate PYTHON=./.venv/bin/python` | 0 | Submission validation passed. |
| `make paper-verify PYTHON=./.venv/bin/python` | 0 | Rebuilt 5-page root `wod2sim.pdf` and ran submission validation. |
| `make verify PYTHON=./.venv/bin/python` | 0 | Lint, conformance, coverage, bootstrap smoke, package build, paper rebuild, and submission validation all passed. |
| `./.venv/bin/python scripts/validate_cvm_submission.py` | 0 | Submission validation passed, including metadata-backed title/author/affiliation/abstract checks, IEEE A4 source-layout checks, LaTeX log warnings, embedded PDF font descriptors, per-manifest `failure_attribution` consistency, summary-level attribution partition checks, and README/paper claim-boundary terms. |

## Latest Submission Gate Refresh

| Command | End UTC | Exit | Result |
|---|---|---:|---|
| `./.venv/bin/python -m pytest -q tests/test_validate_cvm_submission.py` | 2026-07-17T19:35:04Z | 0 | 25 passed, including metadata, embedded-font, layout-hack, and LaTeX-log validation fixtures. |
| `make paper-verify PYTHON=./.venv/bin/python` | 2026-07-17T19:35:04Z | 0 | Rebuilt 5-page root `wod2sim.pdf`; submission validation passed with metadata, source-layout, embedded-font, and LaTeX-log enforcement. |
| `make cvm-check PYTHON=./.venv/bin/python` | 2026-07-17T19:35:04Z | 0 | Ruff passed; conformance passed with 255 passed, 14 skipped, and 15 subtests passed; submission validation passed. |

## Important Warnings

- `make cvm-eval` exits 2 because the configured core matrix still includes
  direct actor-aware rows without the required oracle actor proxy. This is a
  recorded precondition blocker, not a test failure.
- The local validator uses `mutool` and LaTeX log/source checks, including a
  font-descriptor pass that rejects unembedded paper fonts. CI installs Poppler
  and `qpdf` to run `pdfinfo`, `pdffonts`, and `qpdf --check` on the canonical
  paper PDF.
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

The latest refresh also validates the aggregate-level attribution partition:
policy-failure rows cannot exceed policy-behavior rows, claim-valid policy rows
must match policy-behavior-attributable rows, and policy-attributed plus
non-policy-attributed rows must cover the full CVM denominator.
