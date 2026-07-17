# Release Test Report

This report records the validation commands for the CVM release surface. Raw
command logs are intentionally not tracked; rerun these commands from the
repository root to reproduce the checks.

| Command | Result |
|---|---|
| `./scripts/build_cvm_paper.sh` | Passed; rebuilt 5-page root `wod2sim.pdf`. |
| `./.venv/bin/python scripts/validate_cvm_submission.py` | Passed, including metadata-backed title/author/affiliation/abstract checks, IEEE A4 source-layout checks, LaTeX log warnings, embedded PDF font descriptors, manifest-level failure-attribution checks, summary-level attribution partition checks, and README/paper claim-boundary checks. |
| `make paper-verify PYTHON=./.venv/bin/python` | Passed: rebuilt 5-page root `wod2sim.pdf` and ran submission validation. |
| `make conformance PYTHON=./.venv/bin/python` | Passed: 255 passed, 14 skipped, 15 subtests passed. |
| `make demo PYTHON=./.venv/bin/python` | Passed: synthetic demo valid with `valid_claim_evidence=false`. |
| `make cvm-check PYTHON=./.venv/bin/python` | Passed: ruff clean, 255 passed, 14 skipped, 15 subtests passed, validation passed. |
| `make verify PYTHON=./.venv/bin/python` | Passed: lint, conformance, coverage, bootstrap smoke, package build, paper rebuild, and submission validation completed successfully. |
| `make cvm-eval PYTHON=./.venv/bin/python` | Expected exit 2: preserves 36 completed core rows and reports 18 direct-actor proxy blockers. |
| `./.venv/bin/python -m pytest -q` | Passed: 255 passed, 14 skipped, 15 subtests passed. |
| `./.venv/bin/python -m build` | Passed: built source distribution and wheel. |
| `./.venv/bin/pre-commit run --all-files` | Passed without modifying files. |
| `git diff --check` | Run as final whitespace validation. |

Targeted contract selections:

| Selection | Result |
|---|---|
| `tests -k "semantic or route"` | 10 passed, 259 deselected. |
| `tests -k "temporal or resampl"` | 10 passed, 259 deselected, 15 subtests passed. |
| `tests -k "lifecycle or session"` | 10 passed, 259 deselected. |
| `tests -k "plugin or entry_point"` | 5 passed, 264 deselected. |
| `tests -k "deployment or readiness or launch"` | 20 passed, 249 deselected. |
| `tests -k "evidence or audit or benchmark"` | 19 passed, 250 deselected. |
| `tests -k "fault"` | 5 passed, 264 deselected. |

The release claim boundary is intentionally narrower than the test suite:
passing tests support contract behavior and artifact hygiene, while policy
quality and official benchmark claims require separate completed evidence.
The submission validator now fails if a CVM run manifest omits or contradicts
the integration-vs-policy `failure_attribution` record.
It requires the attribution rule to name semantic, temporal, lifecycle,
deployment, and evidence gates before any policy-behavior or policy-failure
claim.
It also fails if README or paper text drops the failure-attribution boundary,
or if the aggregate summary no longer partitions policy-attributable and
non-policy-attributed rows over the complete CVM denominator.
It also validates the public `frames.csv` schema so frame-level timing, route,
trajectory, latency, lifecycle-warning, and policy-status fields cannot
silently disappear from regenerated artifacts.
It now rejects a paper PDF if any discovered font lacks an embedded
`/FontFile`, `/FontFile2`, or `/FontFile3` descriptor.
It also rejects title, author, affiliation, PDF-subject, abstract word-count, or
abstract-source drift against `paper/cvm/metadata.json`.
It rejects manuscript-source page, margin, font-scaling, page-style, and
negative-spacing overrides so the IEEE A4 template remains unmodified.
It rejects unresolved citations/references, multiply defined labels, and
overfull or underfull `\hbox` warnings in the generated LaTeX log.
