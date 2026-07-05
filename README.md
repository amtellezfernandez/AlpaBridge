# WOD2Sim

<p align="center">
  <a href="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml"><img src="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-blue.svg" alt="BSD-3-Clause license"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0f766e.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/evidence-manifest%20%2B%20audit%20%2B%20bundle-d97928.svg" alt="Evidence workflow">
</p>

`WOD2Sim` is an installable Python package and public CLI for adapting
WOD-style driving-policy outputs to NVIDIA AlpaSim's closed-loop external-driver
runtime. It is a bridge and evidence workflow, not a redistributor of AlpaSim,
Waymo assets, private checkpoints, or gated scene caches.

## Media Gallery

The README should show real media from three places: the dataset scene, the
AlpaSim closed-loop rollout, and the WOD2Sim integration/evidence output. Those
assets are not tracked yet because the local candidates live under ignored
`runs/` and `workspace/` paths and may be gated or third-party.

| Media | Status | Expected tracked path |
| --- | --- | --- |
| Dataset frame | Waiting for redistribution-approved WOD/AlpaSim frame | `docs/assets/readme/dataset-frame.jpg` |
| AlpaSim rollout video | Waiting for redistribution-approved rollout clip | `docs/assets/readme/alpasim-rollout.mp4` |
| Integration screenshot | Waiting for a real terminal or UI capture | `docs/assets/readme/integration-terminal.png` |
| Evidence metrics | Waiting for approved local-run metrics export | `docs/assets/readme/evidence-metrics.png` |

See [`docs/readme_media.md`](docs/readme_media.md) for the exact media slots and
the local candidates that should be reviewed before publishing.

## What This Repo Gives You

| Surface | Public without private assets? | Output |
| --- | --- | --- |
| Package install and doctor checks | Yes | importable `wod2sim`, CLI health report |
| Reproduction command planning | Yes | manifest with commands, provenance, and `valid_claim_evidence: false` |
| AlpaSim closed-loop execution | Requires local AlpaSim and gated/user assets | driver logs, audit JSON, support bundle |
| Benchmark packet summary | Yes, if evidence JSON is present | compact JSON across one or more reproduction runs |

## What Is In Scope

- AlpaSim model adapters:
  `spotlight_reflex`, `token_dagger_bc`, and `direct_actor_planner`
- policy-facing signal reconstruction from AlpaSim prediction inputs
- route-waypoint adapter behavior and tracked AlpaSim override files
- local setup, readiness, launch, and scene-batch orchestration
- simulator-side policy code used by the adapter surface
- the paper and its build assets

## What Is Not Bundled

- AlpaSim itself: this repo expects a separate nested AlpaSim checkout
- private checkpoints or large local artifacts from the original research tree
- gated scene assets and local Docker images

## First 5 Minutes

Install and run the public checks:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
wod2sim-doctor
make test
```

Create a public reproduction plan without AlpaSim or gated scene assets:

```bash
wod2sim-reproduce \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim-demo/run \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --json
```

Turn that plan evidence into a benchmark-shaped summary:

```bash
wod2sim-benchmark-summary \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --output /tmp/wod2sim-demo/benchmark-summary.json \
  --json
```

That summary is useful for review, but it intentionally remains
`valid_claim_evidence: false` until the workflow is executed against real local
AlpaSim assets.

## Closed-Loop Evidence

With a local AlpaSim checkout, Docker/GPU runtime, and any model-specific user
artifact, execute the workflow:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --run-dir runs/benchmark_spotlight_reflex_10scene \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene/evidence \
  --json
```

Then publish the compact evidence, not raw gated assets:

```bash
wod2sim-benchmark-summary \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene/evidence \
  --output runs/wod2sim-benchmark-summary.json \
  --strict \
  --json
```

The tracked local evidence summary records one executed `spotlight_reflex`
closed-loop run: 1 scene, 199 audited frames, and 0 sensor failures. See
[`docs/evidence/closed_loop_spotlight_reflex_one_scene.json`](docs/evidence/closed_loop_spotlight_reflex_one_scene.json).

## Demo Media Boundary

This README uses SVG diagrams instead of a checked-in rollout video because raw
AlpaSim/WOD-derived media may contain gated assets. If you have redistribution
rights for a rollout, attach the video to a GitHub Release and link it here.
Until then, the public visual artifact is the evidence trail: manifest, audit
JSON, support-bundle report, hashes, and benchmark summary.

## Runtime Setup

For a fuller first-time setup path and failure triage notes, see
[`docs/integration_guide.md`](docs/integration_guide.md).

If you also want the doctor command to diagnose a real AlpaSim checkout:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim
```

If that checkout is not fully synced yet and you only want host/runtime validation:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim --skip-scene-artifacts
```

If `fresh_3scene` is not fully cached yet, a more reliable first live smoke is:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim --scene-preset front_camera_10scene_smoke
wod2sim-launch --mode both --model spotlight_reflex --scene-preset front_camera_10scene_smoke
```

If you already have the gated USDZ cache in another local checkout, import it into
this repo's nested AlpaSim tree without Docker-breaking absolute symlinks:

```bash
./scripts/import_alpasim_scene_cache.sh --source-root /path/to/other/alpasim
```

## Public Model Surface

This release intentionally exposes a small public launch surface:

- `spotlight_reflex`: checkpoint-free smoke-test adapter
- `token_dagger_bc`: learned policy adapter; requires `--checkpoint /path/to/token_dagger_bc.pt`
- `direct_actor_planner`: planner adapter; requires `--oracle-actor-proxy /path/to/oracle.json`

Research-only presets outside this release are not advertised in the public CLI.

Examples:

```bash
wod2sim-build-oracle-proxy --run-dir /path/to/run --output /path/to/oracle.json
wod2sim-launch --mode print --model spotlight_reflex
wod2sim-launch --mode print --model token_dagger_bc --checkpoint /path/to/token_dagger_bc.pt
wod2sim-launch --mode print --model direct_actor_planner --oracle-actor-proxy /path/to/oracle.json
```

After an executed run, summarize the public driver logs with:

```bash
wod2sim-audit-run --run-dir /path/to/run
wod2sim-audit-run --run-dir /path/to/run --audit-dir /path/to/audit --json
```

To package the key run logs, configs, and audit output into one shareable tarball:

```bash
wod2sim-support-bundle --run-dir /path/to/run
wod2sim-support-bundle --run-dir /path/to/run --output /tmp/run_support_bundle.tar.gz --json
```

One important runtime invariant: if ego pose updates continue while camera timestamps stay frozen, the public adapters now fail fast with a `stale camera stream` error instead of silently planning on stale frames.
Each public model also writes a structured per-frame driver log under `run_dir/driver/`:
`spotlight-log.jsonl`, `selection-log.jsonl`, or `direct-planner-log.jsonl`.
Those records include `sensor_freshness` fields with the latest camera timestamp,
ego pose timestamp, lag, and failure status so upstream camera-pipeline faults are
auditable after the run.
Executed runs also write `run-status.json`, which records the launch mode, current
phase, return codes, aggregate-output status, and key log paths.
Batch runs now preserve a per-scene `diagnostics` block in `batch-status.json`
with each scene's `run-status` summary, driver-log presence, and first camera-pipeline
failure so multi-scene triage does not collapse to `partial` or `missing`.

## Repo Layout

- [`src/wod2sim/simulator/`](src/wod2sim/simulator) contains the
  simulator logic and AlpaSim adapters.
- [`src/wod2sim/cli/commands/`](src/wod2sim/cli/commands) contains the
  runtime-facing command implementations.
- [`scripts/`](scripts) provides top-level entry wrappers for the public workflows.
- [`third_party/alpasim_overrides/`](third_party/alpasim_overrides) contains the tracked
  AlpaSim override files and patch sets needed by the reproduction path.
- [`docs/closed_loop_reproduction.md`](docs/closed_loop_reproduction.md) documents
  the actual closed-loop evidence workflow and gated asset boundaries.
- [`docs/waymo_readiness.md`](docs/waymo_readiness.md) records the remaining gap
  between this research bridge and a broader benchmark or production-grade tool.
- [`paper/`](paper) contains the LaTeX source for the paper.

## Paper

Build the paper with:

```bash
make paper
```

The source lives under [`paper/`](paper). CI publishes the compiled PDF as a build
artifact instead of tracking generated PDFs in git.

## Release Checks

Run the public verification path with:

```bash
make verify
```

Clean generated local artifacts with:

```bash
make clean
```

## Citation

If you use this repository in academic work, cite the software metadata in
[`CITATION.cff`](CITATION.cff) and the paper under [`paper/`](paper).

## License

The repository is distributed under the BSD 3-Clause License. Some packaged
AlpaSim override files carry separate third-party notices; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Production Notes

- The GitHub CI runs lint, coverage, package build, wheel smoke, and paper build.
- Learned presets still depend on external checkpoints not shipped in this repo.
- Full AlpaSim execution still requires a separate checkout, local Docker access, and any gated scene assets.
