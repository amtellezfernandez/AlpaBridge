# Reproduction

`alpabridge-reproduce` records the full setup, readiness, launch, audit, and bundle
workflow in one manifest.

## Plan

A dry plan requires no AlpaSim runtime:

```bash
alpabridge-reproduce \
  --model constant_velocity \
  --scene-id example-scene \
  --run-dir /tmp/alpabridge/run \
  --evidence-dir /tmp/alpabridge/evidence \
  --json
```

The plan is reviewable but reports `valid_claim_evidence: false` because no
closed-loop execution occurred.

## Execute

```bash
alpabridge-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model constant_velocity \
  --scene-preset fresh_3scene \
  --run-dir runs/constant_velocity_fresh_3scene \
  --evidence-dir runs/constant_velocity_fresh_3scene/evidence \
  --json
```

For independent scene retries and timeouts, use `alpabridge-batch` with the same
model arguments. Use `alpabridge-batch-summary` to aggregate a completed batch, and
`alpabridge-benchmark-readiness` to refuse public benchmark readiness until the
minimum executed-scene matrix is present.

## Evidence Packet

An executed run can produce:

| Artifact | Contents |
| --- | --- |
| `closed-loop-reproduction-manifest.json` | Commands, model inputs, scenes, status, provenance, and claim boundary. |
| `run-audit.json` | Driver frames, result counts, and sensor-freshness failures. |
| `support-bundle-report.json` | Included files and exclusions. |
| `support-bundle.tar.gz` | Local logs and normalized audit export. |
| `alpabridge-batch-summary.json` | Multi-scene completion, metrics, and failure taxonomy. |

Raw scene assets, private checkpoints, and rollout media remain local.

## Interpretation

A dry command plan proves only that the package and command surface are
available. A completed integration run additionally needs the driver log,
simulator result, expanded configuration, and audit to agree.
Policy-performance reporting requires representative declared scenes,
appropriate baselines, complete metrics, and failure analysis beyond this
adapter release.
