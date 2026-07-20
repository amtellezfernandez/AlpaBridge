# CLI

The contract-validation matrix (CVM) is referenced in the release targets below.

## Setup And Execution

| Command | Purpose |
| --- | --- |
| `alpabridge-doctor` | Validate the installed package and optional AlpaSim environment. |
| `alpabridge-setup` | Apply and validate the tracked AlpaSim override layer. |
| `alpabridge-ready` | Check platform, local AlpaSim `.venv`, Docker, GPU, image, and scene readiness. |
| `alpabridge-launch` | Materialize or execute one matched driver/wizard run. |
| `alpabridge-batch` | Execute scenes independently with retries and timeouts. |
| `alpabridge-reproduce` | Plan or execute setup through evidence packaging. |

## Inputs And Evidence

| Command | Purpose |
| --- | --- |
| `alpabridge-build-local-cache` | Build or validate a local scene cache. |
| `alpabridge-build-oracle-proxy` | Build the scene-matched actor proxy required by the direct planner. |
| `alpabridge-audit-run` | Normalize driver logs and check sensor freshness. |
| `alpabridge-support-bundle` | Package selected logs, configs, and audit output. |
| `alpabridge-batch-summary` | Aggregate a multi-scene batch. |
| `alpabridge-benchmark-summary` | Aggregate reproduction manifests and run audits. |
| `alpabridge-benchmark-readiness` | Gate public benchmark claims against clean batch summaries. |
| `alpabridge-promote-batch-summary` | Copy a validated local summary to an explicit destination. |
| `alpabridge-evidence` | Inspect AlpaSim runtime metrics. |
| `alpabridge-challenge-driver` | Serve or self-test the AlpaSim E2E-style external-driver compatibility adapter. |
| `alpabridge-waymax-study` | Run the bounded Waymax/WOMD policy-by-route attribution study against a pinned checkout. |

## Quality And Release Targets

| Command | Purpose |
| --- | --- |
| `make conformance` | Run the dependency-light contract conformance tier. |
| `make demo` | Generate the public synthetic contract demo. |
| `make verify` | Run lint, conformance, coverage, smoke, build, paper rebuild, and validation. |
| `make paper` | Rebuild the canonical paper PDF through the CVM paper target. |
| `make paper-verify` | Rebuild the canonical paper PDF and run submission validation. |
| `make cvm-inventory` | Refresh the redacted repository and environment inventory. |
| `make cvm-check` | Run lint, conformance, and CVM submission validation. |
| `make cvm-demo` | Write the synthetic CVM demo under `artifacts/cvm/results/demo`. |
| `make cvm-eval` | Expand the mixed CVM core matrix, preserving completed public-core rows and optional gated blockers. |
| `make cvm-diagnostics` | Generate current-adapter protocol sessions, evaluate paired controlled mutations and valid controls, and record scoped software timings. |
| `make cvm-synthetic` | Execute lifecycle stress, label-withheld fault localization, and the controlled diagnostic experiment. |
| `make cvm-aggregate` | Regenerate aggregate CSV/JSON, LaTeX tables, and figures from CVM results. |
| `make cvm-paper` | Build the paper source and copy the canonical root `alpabridge.pdf`. |
| `make cvm-validate` | Run the CVM paper and release-surface validator. |
| `make cvm-all` | Run the end-to-end CVM release sequence, preserving exit 2 for documented blockers. |

## Developer Targets

| Command | Purpose |
| --- | --- |
| `make test` | Run the test suite without the conformance environment flag. |
| `make lint` | Run Ruff over the repository. |
| `make coverage` | Run the pytest coverage target. |
| `make smoke` | Run the release bootstrap smoke check. |
| `make build` | Build the Python package with `uv build` when available, otherwise `python -m build`. |
| `make clean` | Remove local build, cache, demo, and Python bytecode artifacts. |

Run any command with `--help` for its complete arguments.

`alpabridge-ready` is a launch-readiness check: by default it requires the local
AlpaSim Python environment and `alpasim_wizard` executable because
`alpabridge-launch` needs both even in command-materialization mode. Use
`--skip-local-env` only for host/container diagnostics that are not launch
claims.
