# Patched Upstream AlpaSim Work

This directory is the explicit **patched upstream** zone for the AlpaSim part of the
simulation stack.

Use it when the question is:

- what had to be patched outside the core repo code
- what is first-party adapter code vs modified AlpaSim-side material
- what belongs to the simulator audit surface but is not first-party source

## What This Means

These files are not being presented as untouched third-party source.

They represent upstream AlpaSim surface area that required real project work:

- bug fixes
- bridge changes
- deployment/runtime adjustments
- integration-specific modifications needed to make the simulator transfer path work

So the correct label is:

- **patched upstream work**

not:

- "just external code"

## Contents

- `route_waypoints.patch` — tracked patch for route-waypoint bridge behavior
- `local_checkout.patch` — local checkout patch material
- `Dockerfile.amd64` — runtime image customization for supported hosts
- `src/wizard/**` — tracked wizard/deployment overrides
- `src/driver/**` — tracked external-driver override files

## Boundary Rule

These files are not the main simulator implementation and not the WOD model stack.
They still belong to the simulation audit surface because the AlpaSim reproduction path
depends on them, and because project-authored modifications were made here.

The corresponding first-party integration code lives in:

- [`src/minimal_shot_av/simulator/README.md`](../../src/minimal_shot_av/simulator/README.md)

The corresponding audit / reproduction path lives in the repo-level setup, readiness,
launch, and test workflow documented in the root README.
