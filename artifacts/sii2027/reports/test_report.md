# SII 2027 Test Report

Captured from logs under `artifacts/sii2027/logs/tests/`.

## Required Commands

| Command | Exit | Result |
|---|---:|---|
| `make conformance PYTHON=./.venv/bin/python` | 0 | 188 passed, 14 skipped |
| `make demo PYTHON=./.venv/bin/python` | 0 | synthetic demo generated; benchmark claim false |
| `make sii2027-check PYTHON=./.venv/bin/python` | 0 | lint, conformance, and SII validation passed |
| `./.venv/bin/python -m pytest -q tests` | 0 | 188 passed, 14 skipped |
| `./.venv/bin/python -m pytest -q tests -k "semantic or route"` | 0 | 6 passed, 196 deselected |
| `./.venv/bin/python -m pytest -q tests -k "temporal or resampl"` | 0 | 2 passed, 200 deselected |
| `./.venv/bin/python -m pytest -q tests -k "lifecycle or session"` | 0 | 1 passed, 201 deselected |
| `./.venv/bin/python -m pytest -q tests -k "plugin or entry_point"` | 0 | 2 passed, 200 deselected |
| `./.venv/bin/python -m pytest -q tests -k "deployment or readiness or launch"` | 0 | 16 passed, 186 deselected |
| `./.venv/bin/python -m pytest -q tests -k "evidence or audit or benchmark"` | 0 | 18 passed, 184 deselected |
| `./.venv/bin/python -m pytest -q tests -k "fault"` | 0 | 5 passed, 197 deselected |

## Coverage Interpretation

The filtered commands execute successfully, but several slices are thin. The current
repository has useful existing coverage for route, deployment, evidence, and audit
behavior. The SII lifecycle and fault matrices now execute as public synthetic harnesses,
but pytest coverage for lifecycle session behavior and fault injectors remains thin. The
paper should describe synthetic diagnostics separately from closed-loop experimental findings.

Named/equivalent Phase D coverage is audited in
`artifacts/sii2027/reports/contract_test_audit.md`. The audit finds partial coverage
overall, with the largest remaining gaps in lifecycle session tests and optional-backend
isolation tests.
