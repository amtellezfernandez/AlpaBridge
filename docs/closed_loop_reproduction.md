# Closed-Loop Reproduction

This document separates the public smoke/demo path from the actual
WOD-style-policy to AlpaSim closed-loop claim.

## Claim Boundary

The closed-loop claim is only supported by an executed AlpaSim external-driver
run. A valid evidence run requires:

- a real AlpaSim checkout
- Docker access and NVIDIA container runtime access
- local AlpaSim scene metadata and gated scene artifacts
- a public WOD2Sim model preset
- any model-specific user artifact:
  - `token_dagger_bc`: checkpoint file supplied with `--checkpoint`
  - `direct_actor_planner`: oracle actor-proxy JSON supplied with `--oracle-actor-proxy`

The repository does not redistribute AlpaSim, gated scene assets, WOD-derived
assets, or private checkpoints. A dry-run manifest is useful for review, but it
is not closed-loop evidence.

## Plan Without Private Assets

Anyone can inspect the exact workflow without AlpaSim or gated assets:

```bash
wod2sim-reproduce \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim-repro/run \
  --evidence-dir /tmp/wod2sim-repro/evidence
```

This writes:

```text
/tmp/wod2sim-repro/evidence/closed-loop-reproduction-manifest.json
```

The manifest records the commands that would be run, the required gated inputs,
and the expected evidence files. It sets `valid_claim_evidence: false` because no
closed-loop rollout has executed.

## Execute With User-Provided AlpaSim Assets

For the checkpoint-free public adapter:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --run-dir /tmp/wod2sim-repro/run \
  --evidence-dir /tmp/wod2sim-repro/evidence
```

For `token_dagger_bc`:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model token_dagger_bc \
  --checkpoint /path/to/token_dagger_bc.pt \
  --scene-preset front_camera_10scene_smoke \
  --run-dir /tmp/wod2sim-repro/run \
  --evidence-dir /tmp/wod2sim-repro/evidence
```

For `direct_actor_planner`:

```bash
wod2sim-build-oracle-proxy --run-dir /path/to/source/run --output /tmp/oracle.json

wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model direct_actor_planner \
  --oracle-actor-proxy /tmp/oracle.json \
  --scene-preset front_camera_10scene_smoke \
  --run-dir /tmp/wod2sim-repro/run \
  --evidence-dir /tmp/wod2sim-repro/evidence
```

The command executes these steps:

- `wod2sim-setup`
- `wod2sim-ready`
- `wod2sim-launch --mode both`
- `wod2sim-audit-run`
- `wod2sim-support-bundle`

Use `--skip-setup` only when the target AlpaSim environment is already wired to
the current WOD2Sim checkout or installed wheel.

## Evidence Output

A completed execution writes the reproduction manifest:

```text
closed-loop-reproduction-manifest.json
```

The manifest sets `valid_claim_evidence: true` only when the launch, audit, and
support-bundle steps succeed and the run audit validates the structured driver
log. The evidence directory also contains:

- per-step stdout/stderr logs
- `run-audit.json`
- normalized audit export under `audit/`
- `support-bundle.tar.gz`
- `support-bundle-report.json`

The support bundle packages the run metadata, generated driver/wizard commands,
driver logs, aggregate outputs when present, and normalized audit export.

## Recorded Local Evidence

This repository includes a compact summary of one locally executed
`spotlight_reflex` AlpaSim closed-loop run:

```text
docs/evidence/closed_loop_spotlight_reflex_one_scene.json
```

The summary records the exact command, scene id, return codes, audit counts,
sensor freshness result, and hashes for the local support bundle. The full run
directory and bundle are not tracked because they may contain AlpaSim or
gated-scene-derived artifacts.

## What Cannot Be Redistributed Here

- AlpaSim source, containers, and runtime assets
- gated USDZ scene assets or scene caches
- private or license-restricted checkpoints
- WOD-derived files unless their redistribution rights are explicit

If you publish a result based on this repo, publish the reproduction manifest,
support bundle, exact command line, commit SHA, model artifact provenance, and a
clear statement of which gated assets were used.
