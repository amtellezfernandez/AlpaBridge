# Reproduction

`wod2sim-reproduce` records the full setup, readiness, launch, audit, and bundle
workflow in one manifest.

## Plan

A dry plan requires no AlpaSim runtime:

```bash
wod2sim-reproduce \
  --model token_dagger_bc \
  --checkpoint /path/to/token_dagger_bc.pt \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim/run \
  --evidence-dir /tmp/wod2sim/evidence \
  --json
```

The plan is reviewable but reports `valid_claim_evidence: false` because no
closed-loop execution occurred.

## Execute

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model token_dagger_bc \
  --checkpoint /path/to/token_dagger_bc.pt \
  --scene-preset fresh_3scene \
  --run-dir runs/token_dagger_bc_fresh_3scene \
  --evidence-dir runs/token_dagger_bc_fresh_3scene/evidence \
  --json
```

For independent scene retries and timeouts, use `wod2sim-batch` with the same
model arguments. Use `wod2sim-batch-summary` to aggregate a completed batch.

## Evidence Packet

An executed run can produce:

| Artifact | Contents |
| --- | --- |
| `closed-loop-reproduction-manifest.json` | Commands, model inputs, scenes, status, and claim boundary. |
| `run-audit.json` | Driver frames, result counts, and sensor-freshness failures. |
| `support-bundle-report.json` | Included files and exclusions. |
| `support-bundle.tar.gz` | Local logs and normalized audit export. |
| `wod2sim-batch-summary.json` | Multi-scene completion, metrics, and failure taxonomy. |

Raw scene assets, private checkpoints, and rollout media remain local.

## Claim Boundary

A dry command plan proves only that the release surface is installed. An
integration claim requires an executed run with a successful audit. A policy
performance claim additionally requires declared scenes, baselines, complete
metrics, and failure analysis. This repository currently publishes no policy
benchmark result.
