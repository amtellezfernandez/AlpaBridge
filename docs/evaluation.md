# Evaluation

WOD2Sim should be evaluated as a contract-based integration boundary before it
is evaluated as a policy runtime.

`WOD-style` refers to the policy-interface shape used by logged driving tasks,
not to an official Waymo challenge submission package. Reports should state the
actual task specification, scene source, and asset revision they use.

## Failure Attribution Rule

Separate integration failures from policy failures before reporting any behavior
metric. WOD2Sim uses this operational rule:

| Row state | Attribution |
| --- | --- |
| Route, sensor, temporal, lifecycle, deployment, or evidence contract fails. | Integration/precondition/evidence failure; do not score as policy behavior or policy failure. |
| Row executes and the route/sensor audit passes, but benchmark prerequisites are incomplete. | Contract-valid diagnostic rollout; inspectable, but not a public policy benchmark. |
| Row executes, passes all audits, satisfies the benchmark gate, and is retained in the aggregate denominator. | Policy behavior may be analyzed and compared; policy failure additionally requires a retained policy-layer failure. |

This boundary is the main evaluation object. It prevents a route adapter bug,
stale observation, missing actor proxy, or incomplete manifest from being
misreported as a bad driving policy. A collision, timeout, invalid trajectory,
or degraded progress metric inside a contract-invalid row is an integration
symptom until the claim-valid gate passes. Passing that gate permits policy
behavior attribution; it does not automatically make the event a policy failure.

## Contract Checks

- AlpaSim discovers only the declared WOD2Sim model entry points.
- Route waypoints reach policy code without being reduced to a command alone.
- Camera, ego-motion, route, and structured hazards form a stable policy signal.
- Five-second policy trajectories preserve native-rate samples, use origin-anchored
  endpoint interpolation when resampled, and recompute runtime headings.
- A replay-identity adapter preserves logged trajectory points through the shared
  output contract.
- Late session messages and repeated close events do not corrupt a batch.
- Run configuration and evidence artifacts are materialized before execution.
- Claim-valid audits require `route_source=alpasim_waypoints` for every driver-log frame.

These checks are covered by the dependency-light [core conformance tier](conformance.md).
Torch-dependent checkpoint tests are skipped from conformance and remain optional
for learned-policy validation.

The [ungated demo](demo.md) exercises the same audit and support-bundle formats
on synthetic local artifacts and reports route-loss and lane-offset diagnostics
on public synthetic geometry. These diagnostics make the integration boundary
inspectable, but they are not an AlpaSim rollout or policy result.

## Policy Evaluation

A report using WOD2Sim should declare:

| Category | Required reporting |
| --- | --- |
| Scene set | IDs or preset, count, exclusions, and asset revision. |
| Model | Adapter, checkpoint/proxy provenance, and configuration. |
| Baselines | At least replay/constant velocity, route following, and an unmodified AlpaSim path where applicable. |
| Behavior | Collision, at-fault collision, off-road, wrong-lane, progress, completion, and timeout rates. |
| Runtime | Valid-frame ratio, sensor freshness, action latency, late messages, and process failures. |
| Evidence | Manifest, AlpaSim checkout and Docker image provenance, audit, summary, hashes, and failed-scene taxonomy. |

Results must use scenes as statistical units. Partial attempts and command plans
must not be promoted as benchmark summaries. Runs that fall back to
`route_source=command_proxy` are adapter triage evidence, not policy benchmark
evidence, because route geometry did not reach the policy contract.

## Benchmark Readiness Gate

Use `wod2sim-batch-summary` for each executed driver batch, then gate the public
claim with:

```bash
wod2sim-benchmark-readiness \
  --batch-summary summaries/constant_velocity.json \
  --batch-summary summaries/route_following.json \
  --batch-summary summaries/token_dagger_bc.json \
  --output summaries/benchmark-readiness.json \
  --json
```

The default gate requires at least 15 unique executed scenes, clean closed-loop
batch summaries only, route-waypoint-backed audited frames, behavior/runtime
metrics, and three baseline families: replay or constant velocity, route
following, and `token_dagger_bc`. It returns nonzero until those conditions are
met. This is intentional: the command prevents demo artifacts, command plans,
or partial smoke runs from being mistaken for a claim-ready public benchmark
result.

## Current Status

The release checks package, semantic, temporal, lifecycle, deployment, and
evidence contracts. The contract-validation matrix (CVM) includes completed
dependency-light closed-loop diagnostic rows on locally available gated scene
assets, completed semantic route-boundary ablations, and public synthetic
lifecycle/fault diagnostics.
The completed full-contract and semantic-ablation rollouts are the current
integration-effectiveness evidence. Synthetic lifecycle/fault rows are secondary
service-harness conformance diagnostics only, and blocked rows are retained as
denominator/context rather than success metrics.

The release does not include a public checkpoint, a redistributable scene
subset, verified scene-category coverage, direct-actor temporal ablation
results, or a claim-ready closed-loop policy benchmark.
