# Conformance

The core conformance tier is the dependency-light contract check for WOD2Sim.
It is intended for CI and for reviewers who do not have AlpaSim scene assets,
Docker, a GPU, torch, or private checkpoints.

```bash
make conformance
```

`make conformance` sets `WOD2SIM_CORE_CONFORMANCE=1` and runs the public test
suite with learned-policy checkpoint tests skipped. This keeps the core tier
stable across machines that may or may not have torch installed.

## Contract Coverage

| Contract property | Evidence in the core tier |
| --- | --- |
| Public model registry is curated | Entry-point and installed-doctor tests require `constant_velocity`, `route_following`, `token_dagger_bc`, and `direct_actor_planner`. |
| Route geometry reaches policy code | Signal tests require `route_source=alpasim_waypoints` when route waypoints are present. |
| Command-proxy fallback is not claim-valid | Audit, batch-summary, and benchmark-summary tests invalidate command-proxy route evidence. |
| Scene signal is behavior-neutral by default | Signal tests keep brightness/dynamics risk diagnostic-only unless structured hazards are present. |
| Trajectory output preserves adapter identity | Resampling identity, endpoint interpolation, and replay-identity tests cover the shared output contract. |
| Launch state is materialized | Setup and launcher tests check command files, metadata, AlpaSim checkout provenance, and Docker-image inspection fields. |
| Evidence can be audited without gated assets | Audit, support-bundle, batch-summary, benchmark-summary, and reproduction-manifest tests run on synthetic local artifacts. |

## Out Of Scope

The core tier is not a driving benchmark. It does not execute AlpaSim rollouts,
does not validate a learned checkpoint, and does not prove collision, progress,
or off-road metrics. Benchmark claims still require executed scenes, baselines,
and failure analysis as described in [Evaluation](evaluation.md).

Torch-dependent token-policy tests remain part of the normal test suite when
torch is installed, but they are intentionally excluded from core conformance so
CI can prove the integration contract without private model artifacts.
