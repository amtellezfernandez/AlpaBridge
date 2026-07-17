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

Run any command with `--help` for its complete arguments.

`wod2sim-ready` is a launch-readiness check: by default it requires the local
AlpaSim Python environment and `alpasim_wizard` executable because
`wod2sim-launch` needs both even in command-materialization mode. Use
`--skip-local-env` only for host/container diagnostics that are not launch
claims.
