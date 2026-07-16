# Evaluation

WOD2Sim should be evaluated as an adapter contract before it is evaluated as a
policy runtime.

## Contract Checks

- AlpaSim discovers only the declared WOD2Sim model entry points.
- Route waypoints reach policy code without being reduced to a command alone.
- Camera, ego-motion, route, and structured hazards form a stable policy signal.
- Five-second policy trajectories are resampled to the configured runtime rate.
- Late session messages and repeated close events do not corrupt a batch.
- Run configuration and evidence artifacts are materialized before execution.

These checks are covered by the dependency-light test suite. Torch-dependent
checkpoint tests are skipped when Torch is unavailable.

## Policy Evaluation

A report using WOD2Sim should declare:

| Category | Required reporting |
| --- | --- |
| Scene set | IDs or preset, count, exclusions, and asset revision. |
| Model | Adapter, checkpoint/proxy provenance, and configuration. |
| Baselines | At least replay/constant velocity, route following, and an unmodified AlpaSim path where applicable. |
| Behavior | Collision, at-fault collision, off-road, wrong-lane, progress, completion, and timeout rates. |
| Runtime | Valid-frame ratio, sensor freshness, action latency, late messages, and process failures. |
| Evidence | Manifest, audit, summary, hashes, and failed-scene taxonomy. |

Results must use scenes as statistical units. Partial attempts and command plans
must not be promoted as benchmark summaries.

## Current Status

The release validates package, adapter, launch, and evidence contracts. It does
not include a public checkpoint or claim-ready closed-loop benchmark result.
