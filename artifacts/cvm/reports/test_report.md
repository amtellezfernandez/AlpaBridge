# Release Test Report

This report records the validation commands for the CVM release surface. Raw
command logs are intentionally not tracked; rerun these commands from the
repository root to reproduce the checks.

| Command | Result |
|---|---|
| `./scripts/build_cvm_paper.sh` | Passed; rebuilt 5-page root `wod2sim.pdf`. |
| `./.venv/bin/python scripts/validate_cvm_submission.py` | Passed. |
| `make cvm-check PYTHON=./.venv/bin/python` | Passed: ruff clean, 226 passed, 14 skipped, 15 subtests passed, validation passed. |
| `make cvm-eval PYTHON=./.venv/bin/python` | Expected exit 2: preserves 36 completed core rows and reports 18 direct-actor proxy blockers. |
| `./.venv/bin/python -m pytest -q` | Passed: 227 passed, 14 skipped, 15 subtests passed. |
| `./.venv/bin/python -m build` | Passed: built source distribution and wheel. |
| `./.venv/bin/pre-commit run --all-files` | Failed: `ruff-format` would reformat 52 files; broad formatting diff not retained. |
| `git diff --check` | Run as final whitespace validation. |

Targeted contract selections:

| Selection | Result |
|---|---|
| `tests -k "semantic or route"` | 9 passed, 232 deselected. |
| `tests -k "temporal or resampl"` | 10 passed, 231 deselected, 15 subtests passed. |
| `tests -k "lifecycle or session"` | 10 passed, 231 deselected. |
| `tests -k "plugin or entry_point"` | 5 passed, 236 deselected. |
| `tests -k "deployment or readiness or launch"` | 20 passed, 221 deselected. |
| `tests -k "evidence or audit or benchmark"` | 19 passed, 222 deselected. |
| `tests -k "fault"` | 5 passed, 236 deselected. |

The release claim boundary is intentionally narrower than the test suite:
passing tests support contract behavior and artifact hygiene, while policy
quality and official benchmark claims require separate completed evidence.
