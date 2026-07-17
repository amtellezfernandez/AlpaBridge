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
| `git diff --check` | Run as final whitespace validation. |

The release claim boundary is intentionally narrower than the test suite:
passing tests support contract behavior and artifact hygiene, while policy
quality and official benchmark claims require separate completed evidence.
