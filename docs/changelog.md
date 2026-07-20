# Changelog

All notable public release changes are tracked here.

## Unreleased - 2026-07-20

- Added an inference adapter and four-arm replay for NAVSIM's official
  EgoStatusMLP seed-0 checkpoint.
- Made route-geometry diagnostics conditional on each policy's declared input
  signature and added a command-native learned negative control.
- Added schema-v3 trajectory cardinality telemetry and fixed serialization to
  retain the current pose plus every predicted future waypoint.
- Regenerated the real-camera comparison video, replay evidence, diagnostics,
  tables, and paper from executed runs.

## 0.1.0 - 2026-07-17

- Renamed the installable release surface to `wod2sim`.
- Added public AlpaSim adapters for `constant_velocity`, `route_following`, `token_dagger_bc`, and `direct_actor_planner`.
- Added setup, readiness, launch, batch, audit, and support-bundle CLI commands.
- Added manifest, audit, support-bundle, and batch-summary evidence contracts.
- Standardized runtime configuration on the `WOD2SIM_` environment namespace.
- Consolidated the public documentation and added the paper PDF.
- Added packaged AlpaSim override files with third-party attribution.
- Added full-test, wheel-smoke, fresh-checkout, and paper-build CI coverage.
