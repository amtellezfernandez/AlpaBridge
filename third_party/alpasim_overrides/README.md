# Tracked AlpaSim Overrides

This directory is the explicit AlpaSim override zone for the simulation stack.

Use it when the question is:

- what had to be changed outside the core repo code
- what is first-party adapter code vs modified AlpaSim-side material
- what belongs to the simulator audit surface but is not first-party source

## What This Means

These files are not being presented as untouched third-party source.

They represent AlpaSim surface area that required project work:

- bug fixes
- adapter changes
- deployment/runtime adjustments
- integration-specific modifications needed to make the simulator transfer path work

Treat this directory as repo-owned integration material layered on top of AlpaSim,
not as an implicit runtime dependency on some separate legacy package.

## Contents

- `session_metadata.patch`, `local_checkout.patch` — `git format-patch`-style
  patches against the pinned AlpaSim release, applied by `alpabridge-setup`.
  Each is self-labeling: its `Subject:` line and commit body are the
  description, so there's no separate, driftable prose summary of what it
  changes to keep in sync - read the patch file itself (`head -20 <patch>`).
- (`Dockerfile.amd64` was removed 2026-08-12. It was a stale single-stage fork of a
  pre-multi-arch upstream `Dockerfile`, referenced by no code path, and its own header told
  you to build it as `alpasim-base:0.66.0` — the exact tag AlpaBridge pins. An image built
  that way has none of `dcgm-exporter`, `datacenter-gpu-manager`, `prometheus`,
  `TARGETARCH` or the `recipes` extra, and upstream's compose now *always* adds a
  prometheus service from that image, so it could not run a rollout. Upstream's own
  `Dockerfile` selects the base by `TARGETARCH`, which makes a separate amd64 file
  obsolete.)
- `src/wizard/**` — tracked wizard/deployment overrides
- `src/driver/**` — tracked external-driver override files
- everything else (`*.md` + `.patch` pairs, e.g. `arm64-docker-build.md`) —
  proposals for fixing something in AlpaSim itself rather than continuing to
  patch around it locally. Every override above is, in that sense, already
  an implicit upstream proposal - these are just the ones written up for a
  real PR. Each is one `.md` (why, the change, verification performed, how
  to open it) plus a `git am`-ready `.patch`, verified against upstream
  AlpaSim's actual current `main` - not the pinned release the applied
  overrides above target, since a PR is opened against `main`. That's also
  why a proposal isn't necessarily redundant with a same-named override
  above even when both touch the same underlying fix: the proposal may
  carry content (a newer AlpaSim feature, an added upstream test) that
  doesn't exist yet at the pinned release. None of these are opened as
  real PRs yet; `git am` the patch into your own AlpaSim fork and push
  when ready. Once something merges upstream, note that in the proposal's
  `.md` rather than deleting it, so the "why did we carry this" history
  survives (see `docker-compose-gpu-conditional-OBSOLETE.md` for the
  pattern - a proposal that turned out moot, kept so it isn't
  re-investigated).

A file only ever appears as *either* a patch hunk *or* a full tracked copy
here, never both - `alpabridge-setup` applies patches first and then copies
full-file overrides on top, so a hunk touching the same file as a copy would
be silently discarded (the copy always wins).

## Boundary Rule

These files are not the main simulator implementation and not the policy-adapter model stack.
They still belong to the simulation audit surface because the AlpaSim reproduction
path uses them, and because project-authored modifications were made here.

The corresponding first-party integration code lives in:

- [`src/alpabridge/simulator/`](../../src/alpabridge/simulator/)

The corresponding audit / reproduction path lives in the repo-level setup, readiness,
launch, and test workflow documented in the root README and
[`docs/README.md`](../../docs/README.md).

## Licensing

Files in this tree that carry an NVIDIA copyright header (`SPDX-License-Identifier:
Apache-2.0`, `Copyright (c) 2025-2026 NVIDIA Corporation`) are derived from NVIDIA
AlpaSim and are redistributed, with project-authored modifications, under the
Apache License 2.0. See `LICENSES/THIRD_PARTY_NOTICES.md` and
`LICENSES/Apache-2.0.txt` at
the repository root. Everything else in the repository is BSD 3-Clause.

## Baseline: re-verification owed after the August 2026 sync

Both applied patches (`local_checkout.patch`, `session_metadata.patch`) were
re-authored on 2026-08-12 against `NVlabs/alpasim` `main` @ `1e801ca` and verified
to apply cleanly, in `sorted()` order, to a pristine checkout of it.

The **proposals** in this directory (`*.md` + `.patch` pairs) still carry
"verified against `3032e0c`" in their status lines, and `3032e0c` predates the
August 2026 public sync — a 167-file release that rewrote `driver/main.py`
(+390/-304), moved `EgoDriverService` from async `grpc.aio` to sync `grpc`,
reworked `models/base.py`, and added the Alpamayo 2 driver. **Do not `git am` any
proposal onto a current checkout on the strength of its old status line.**

Measured 2026-08-12 with `git apply --check` against a pristine clone of `main`
@ `1e801ca`. This says only whether a patch still *applies* — a green row still
needs its verification steps re-run before the PR is opened:

| proposal | applies to `1e801ca` | note |
| --- | --- | --- |
| `cameraframe-type-mismatch.patch` | yes | re-run verification, then openable |
| `route-generator-plugin.patch` | yes | re-run verification, then openable |
| `utils-rs-negative-zero-serialization.patch` | yes | re-run verification, then openable |
| `session-event-idempotency.patch` | no | same `driver/main.py` rewrite that broke `local_checkout.patch`; the re-authored guards in that patch are the content to regenerate this from |
| `lazy-model-imports.patch` | no | `models/__init__.py` gained `Alpamayo2Model`; must cover it, as the applied override now does |
| `docker-local-extras.patch` | no | `pyproject.toml`'s `all` gained `alpasim-trafficsim` and a `recipes` extra was added; re-authored content already in `local_checkout.patch` |
| `arm64-docker-build.patch` | no | **Content already re-authored into `local_checkout.patch` and verified by a real ARM64 build on the GB10 against `1e801ca`** (33.1GB image, all four arm64 branches confirmed firing, 7/7 packages importing, CUDA up on GB10). The fixes had to move into the applied override because setup never applies proposals. Re-cut this patch from that override before opening upstream — see that `.md` |
| `plugin-config-passthrough.patch` | no | context drift only — `ModelConfig` replaced `use_classifier_free_guidance_nav: bool` with a weight-based field and expanded its docstring. The proposed `extra: dict[str, Any]` pass-through is still absent upstream, so the intent stands; only the hunk context needs refreshing |
| `route-waypoints-in-prediction-input.patch` | no | superseded upstream — see that `.md`; do not reopen |
