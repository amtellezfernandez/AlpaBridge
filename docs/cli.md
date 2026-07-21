# CLI

## Setup And Execution

| Command | Purpose |
| --- | --- |
| `alpabridge-doctor` | Validate the installed package and optional AlpaSim environment. |
| `alpabridge-setup` | Apply and validate the tracked AlpaSim override layer. |
| `alpabridge-ready` | Check platform, local AlpaSim environment, Docker, GPU, image, and scene readiness. |
| `alpabridge-launch` | Materialize or execute one matched driver and AlpaSim run. |
| `alpabridge-batch` | Execute scenes independently with retries and timeouts. |
| `alpabridge-reproduce` | Plan or execute setup through evidence packaging. |

## Inputs And Run Records

| Command | Purpose |
| --- | --- |
| `alpabridge-build-local-cache` | Build or validate a local scene cache. |
| `alpabridge-build-oracle-proxy` | Build the scene-matched actor proxy required by the direct planner. |
| `alpabridge-audit-run` | Normalize driver logs and check route and sensor inputs. |
| `alpabridge-support-bundle` | Package selected logs, configs, and audit output. |
| `alpabridge-batch-summary` | Aggregate a multi-scene batch. |
| `alpabridge-benchmark-summary` | Aggregate reproduction manifests and run audits. |
| `alpabridge-benchmark-readiness` | Check whether a requested public benchmark matrix is complete. |
| `alpabridge-promote-batch-summary` | Copy a validated local summary to an explicit destination. |
| `alpabridge-evidence` | Inspect AlpaSim runtime metrics. |
| `alpabridge-challenge-driver` | Serve or self-test the AlpaSim E2E-style external driver. |

## Development Targets

| Command | Purpose |
| --- | --- |
| `make test` | Run the test suite. |
| `make lint` | Run Ruff over the repository. |
| `make conformance` | Run the dependency-light adapter conformance tier. |
| `make coverage` | Run the test suite with the coverage gate. |
| `make smoke` | Install a fresh copied checkout and exercise the public CLI. |
| `make build` | Build the wheel and source distribution. |
| `make verify` | Run lint, conformance, coverage, smoke, and build. |
| `make clean` | Remove local build, cache, and Python bytecode artifacts. |

Run any command with `--help` for its complete arguments.

`alpabridge-ready` is a launch-readiness check. By default it requires the local
AlpaSim Python environment and `alpasim_wizard` executable because
`alpabridge-launch` needs both even when only materializing commands. Use
`--skip-local-env` only for host or container diagnostics.

## Conformance Tier

`make conformance` sets `ALPABRIDGE_CORE_CONFORMANCE=1` and runs the public
test suite with learned-policy checkpoint tests skipped — the
dependency-light adapter check intended for CI and for reviewers without
AlpaSim scene assets, Docker, a GPU, torch, or private checkpoints. This
keeps the core tier stable across machines that may or may not have torch
installed.

| Adapter property | Evidence in the core tier |
| --- | --- |
| Public model registry is curated | Entry-point and installed-doctor tests expose `constant_velocity`, `route_following`, `token_dagger_bc`, and `direct_actor_planner`; only the first two are dependency-light public-core models. |
| Route geometry reaches policy code | Signal tests require `route_source=alpasim_waypoints` when route waypoints are present. |
| Command-proxy fallback is visible | Audit, batch-summary, and benchmark-summary tests retain route provenance. |
| Scene signal is behavior-neutral by default | Signal tests keep brightness/dynamics risk diagnostic-only unless structured hazards are present. |
| Trajectory output preserves adapter identity | Resampling identity, endpoint interpolation, and replay-identity tests cover the shared output contract. |
| Launch state is materialized | Setup and launcher tests check command files, metadata, AlpaSim checkout provenance, and Docker-image inspection fields. |
| Evidence can be audited without gated assets | Audit, support-bundle, batch-summary, benchmark-summary, and reproduction-manifest tests run on synthetic local artifacts. |

The core tier is not a driving benchmark. It does not execute AlpaSim
rollouts, validate a learned checkpoint, or prove collision, progress, or
off-road performance — those results require executed representative
scenes, appropriate baselines, and failure analysis. Torch-dependent
token-policy tests remain part of the normal test suite when torch is
installed, but are excluded from core conformance so CI can verify the
public adapter without private model artifacts. Direct-actor proxies,
learned checkpoints, and restricted scene assets are optional gated
extensions for live evaluation, not prerequisites for core conformance.
