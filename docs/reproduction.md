# Reproduction

`wod2sim-reproduce` records the full setup, readiness, launch, audit, and bundle
workflow in one manifest.

## Plan

A dry plan requires no AlpaSim runtime:

```bash
wod2sim-reproduce \
  --model constant_velocity \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim/run \
  --evidence-dir /tmp/wod2sim/evidence \
  --json
```

The plan is reviewable but reports `valid_claim_evidence: false` because no
closed-loop execution occurred.

For an ungated artifact walkthrough, run:

```bash
make demo
```

This writes a synthetic run directory with an audit, support bundle, aggregate
JSON, and SVG visual. It does not execute AlpaSim and must not be reported as a
policy metric.

## Execute

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model constant_velocity \
  --scene-preset fresh_3scene \
  --run-dir runs/constant_velocity_fresh_3scene \
  --evidence-dir runs/constant_velocity_fresh_3scene/evidence \
  --json
```

For independent scene retries and timeouts, use `wod2sim-batch` with the same
model arguments. Use `wod2sim-batch-summary` to aggregate a completed batch, and
`wod2sim-benchmark-readiness` to refuse public benchmark readiness until the
minimum executed-scene matrix is present.

## Evidence Packet

An executed run can produce:

| Artifact | Contents |
| --- | --- |
| `closed-loop-reproduction-manifest.json` | Commands, model inputs, scenes, status, provenance, and claim boundary. |
| `run-audit.json` | Driver frames, result counts, and sensor-freshness failures. |
| `support-bundle-report.json` | Included files and exclusions. |
| `support-bundle.tar.gz` | Local logs and normalized audit export. |
| `wod2sim-batch-summary.json` | Multi-scene completion, metrics, and failure taxonomy. |

Raw scene assets, private checkpoints, and rollout media remain local.

## Claim Boundary

A dry command plan proves only that the release surface is installed. An
integration claim requires an executed run with a successful audit. A policy
performance claim additionally requires declared scenes, route-waypoint-backed
driver logs, AlpaSim checkout and Docker image provenance, baselines, complete
metrics, failure analysis, and a passing `wod2sim-benchmark-readiness` report.
This repository currently publishes no policy benchmark result.

If any route, sensor, temporal, lifecycle, deployment, or evidence gate fails,
classify the row as an integration/precondition/evidence failure. Do not count
that row as a policy failure, even if the rollout contains a collision,
off-road event, timeout, or degraded progress metric.
