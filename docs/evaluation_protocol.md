# Evaluation Protocol

WOD2Sim is an adapter and evidence layer for closed-loop evaluation. It should
not be read as a new autonomous driving policy, a new simulator, or a full
Waymo-to-AlpaSim scene converter.

The precise claim is:

> WOD2Sim bridges WOD-style policy interfaces to AlpaSim closed-loop execution
> and records the artifacts needed to audit that execution.

## Claim Boundary

Supported claims:

- A WOD-style trajectory policy can be exposed as an AlpaSim external driver.
- Route geometry, launch state, and simulator lifecycle behavior can be made
  explicit at the driver boundary.
- Closed-loop runs can emit manifests, audits, support-bundle reports, hashes,
  and benchmark summaries without redistributing gated assets.

Unsupported claims:

- WOD2Sim is not a new driving model.
- WOD2Sim is not a full Waymo Open Dataset scene-to-AlpaSim converter.
- WOD2Sim does not redistribute Waymo data, AlpaSim assets, private checkpoints,
  rollout videos, or support bundles.
- One recorded scene is integration evidence, not a broad benchmark result.

## Baselines

Use these baselines when making benchmark claims:

| Baseline | Purpose |
| --- | --- |
| Open-loop WOD-style evaluation | Shows what log-only evaluation can and cannot reveal. |
| Replay policy | Checks simulator plumbing without policy intelligence. |
| Constant-velocity or route-following driver | Provides a closed-loop sanity baseline. |
| Stock AlpaSim external-driver path | Shows what the WOD2Sim adapter adds. |
| WOD2Sim without route reconstruction | Ablates route geometry preservation. |
| WOD2Sim without lifecycle hardening | Ablates robust session handling. |

The strongest result is a paired example where the same policy appears acceptable
under open-loop evaluation but fails differently under closed-loop execution.

## Metrics

Closed-loop reports should include:

| Metric group | Examples |
| --- | --- |
| Driving outcome | collision rate, off-road rate, route progress, scenario completion, timeout rate |
| Runtime validity | valid-frame ratio, sensor freshness, action latency, late-message rate |
| Evidence validity | manifest present, audit valid, support bundle valid, support bundle hash present |
| Failure taxonomy | route drift, stale observations, heading-error compounding, recovery failure, lifecycle crash |

## Scene Coverage

A workshop-scale evaluation should cover at least a small multi-scene set across
straight driving, turns, dense traffic, route merges, occlusion, and stop/go
cases. A stronger benchmark claim should scale to dozens of scenes and report
success/failure counts per route type.
