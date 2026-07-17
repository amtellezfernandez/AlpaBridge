# CLI

## Setup And Execution

| Command | Purpose |
| --- | --- |
| `wod2sim-doctor` | Validate the installed package and optional AlpaSim environment. |
| `wod2sim-setup` | Apply and validate the tracked AlpaSim override layer. |
| `wod2sim-ready` | Check platform, local AlpaSim `.venv`, Docker, GPU, image, and scene readiness. |
| `wod2sim-launch` | Materialize or execute one matched driver/wizard run. |
| `wod2sim-batch` | Execute scenes independently with retries and timeouts. |
| `wod2sim-reproduce` | Plan or execute setup through evidence packaging. |

## Inputs And Evidence

| Command | Purpose |
| --- | --- |
| `wod2sim-build-local-cache` | Build or validate a local scene cache. |
| `wod2sim-build-oracle-proxy` | Build the actor proxy required by the direct planner. |
| `wod2sim-audit-run` | Normalize driver logs and check sensor freshness. |
| `wod2sim-support-bundle` | Package selected logs, configs, and audit output. |
| `wod2sim-batch-summary` | Aggregate a multi-scene batch. |
| `wod2sim-benchmark-summary` | Aggregate reproduction manifests and run audits. |
| `wod2sim-benchmark-readiness` | Gate public benchmark claims against clean batch summaries. |
| `wod2sim-promote-batch-summary` | Copy a validated local summary to an explicit destination. |
| `wod2sim-evidence` | Inspect AlpaSim runtime metrics. |

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
| `make cvm-eval` | Expand the configured CVM core matrix, preserving completed and blocked rows. |
| `make cvm-synthetic` | Execute dependency-light lifecycle-stress and fault-injection diagnostics. |
| `make cvm-aggregate` | Regenerate aggregate CSV/JSON, LaTeX tables, and figures from CVM results. |
| `make cvm-paper` | Build the paper source and copy the canonical root `wod2sim.pdf`. |
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

`wod2sim-ready` is a launch-readiness check: by default it requires the local
AlpaSim Python environment and `alpasim_wizard` executable because
`wod2sim-launch` needs both even in command-materialization mode. Use
`--skip-local-env` only for host/container diagnostics that are not launch
claims.
