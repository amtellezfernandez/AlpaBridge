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
- Route waypoints reach policy code when the active policy declares geometry as
  required; command-native policies are audited against their own signature.
- Camera, ego-motion, route, and structured hazards form a stable policy signal.
- Five-second policy trajectories preserve native-rate samples, use origin-anchored
  endpoint interpolation when resampled, and recompute runtime headings.
- Final protocol serialization rejects empty trajectories, point/heading count
  mismatches, and non-finite coordinates or headings.
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

## Controlled Diagnostic Evaluation

Run `make cvm-diagnostics` to regenerate 15 separate sessions through the
current adapter. The trace contains 405 events and 120 drive calls, all with an
explicit finite serialized-trajectory result. Each valid session is paired with
one predefined single-fault mutation across the five contracts. Mutation and
detection are separate: the detector receives events and runtime context, while
the scorer retains the expected label.

The current artifact reports WOD2Sim at 30/30 correct classifications, 15/15
fault localizations, and 0/15 control false positives. The executable
completion-and-metrics gate is correct on 15/30 and detects no faults. All 15
discordant pairs favor WOD2Sim on this declared suite. These are exact
descriptive counts; no population confidence interval or hypothesis test is
reported because neither sessions nor fault operators are independently
sampled from a defined population. The completion gate is not a substitute for
another integration framework.

Post-parse detector execution latency is measured over 3,000 fault-case calls:
28.096 us median and 55.774 us p95. The guarded in-process adapter Drive path is
617.549 us median and 897.100 us p95. Across 1,000 randomized paired measurements
rotating over 15 valid sessions, its camera-set and freshness-check
increment is 68.871 us median and 309.613 us p95; guarded and unchecked
trajectories and headings are identical. Context-length validation remains
active in both arms. The adapter measurement includes input
assembly, prediction, serialization, finite-output validation, reasoning
parsing, and in-memory telemetry. The measurements exclude gRPC transport, file
I/O, simulator work, and human investigation. They do not establish end-to-end
runtime overhead or time-to-diagnosis.

The retained evaluator-owned AlpaSim trace remains separate interface-conformance
evidence: it records 197 drive calls meeting the 100-ms target. Its earlier
telemetry schema does not include the explicit finite-output field and is not
used as the mutation source.

## Executed Protocol Replay

`scripts/run_alpasim_replay_demo.sh` replays one hash-pinned official AlpaSim
integration recording through four live current-schema WOD2Sim gRPC services.
The policy families are route following and NAVSIM's official learned
EgoStatusMLP seed-0 baseline. Each runs once with all 20 route points retained
and once with only the derived command. All arms receive identical session,
camera, egomotion, route, and `Drive` messages.

Each arm returns 60/60 finite, nonstationary trajectories and meets the 100 ms
latency target. Removing geometry produces `semantic.command_only` only for
route following and changes 56/60 paired endpoints. EgoStatusMLP declares
velocity, acceleration, and command inputs but no route geometry; both arms
therefore pass and all 60 output pairs are exactly equal. This is a
policy-signature negative control.

Route-following full/reduced client-to-service latency is 3.769/4.833 ms
median/p95 and 3.104/3.958 ms. EgoStatusMLP full/reduced latency is
4.715/5.945 ms and 4.943/6.963 ms.

These are loopback transport-inclusive service measurements, not a reactive
simulator runtime or format-overhead comparison. The recorded future camera and
ego-state sequence is unchanged by service output, the arms run once in a fixed
order, and no human time-to-diagnosis study is performed.

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
or partial bootstrap/conformance checks from being mistaken for a claim-ready
public benchmark result.

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
Controlled trace mutations add case/control classification, an executable
status-only comparator, post-parse detector execution latency, and a paired
guard-path increment on the dependency-light path. They do not support human
time-to-diagnosis, end-to-end runtime, or superiority over another integration
framework.
The separate current-schema replay adds bounded client-to-service gRPC latency
and a real-camera diagnostic video. It remains non-reactive and does not extend
the claim to simulator runtime, format overhead, or empirical generalization
across frameworks.
The public release core is the dependency-light adapter path. Direct-actor,
learned-checkpoint, restricted-scene, and complete-benchmark dependencies are
optional gated extensions, not release-core dependencies.

The release does not redistribute a checkpoint or scene subset and does not
provide verified scene-category coverage, direct-actor temporal ablation
results, a visual learned-policy evaluation, or a claim-ready closed-loop
policy benchmark. The official NAVSIM checkpoint is downloaded and hash-checked
only for the bounded protocol replay.
