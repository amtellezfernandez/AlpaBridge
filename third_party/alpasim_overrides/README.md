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

- `route_waypoints.patch`, `local_checkout.patch` — `git format-patch`-style
  patches against the pinned AlpaSim release, applied by `alpabridge-setup`.
  Each is self-labeling: its `Subject:` line and commit body are the
  description, so there's no separate, driftable prose summary of what it
  changes to keep in sync - read the patch file itself (`head -20 <patch>`).
- `Dockerfile.amd64` — runtime image customization for supported hosts
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
