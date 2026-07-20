# Changelog

All notable public release changes are tracked here.

## Unreleased - 2026-07-20

- Added a hash-pinned Waymax/WOMD factorial study with route following and
  constant velocity under full route geometry and an intervention-defined
  command proxy.
- Retained scenario-level evidence for 20 bundled TFExamples: 19 paired
  scenarios, 3,800 steps, selective route-following divergence, exact
  constant-velocity invariance, and policy-signature-aware audit decisions.
- Added a three-panel causal figure generated from the retained run and made it
  the primary README and paper result.
- Rebuilt the executed replay media around the causal boundary mutation:
  identical raw messages, an explicit `20 waypoints -> LEFT only` ablation,
  shared meter axes, the measured endpoint miss, and unobstructed paired
  camera controls.
- Moved the example to the top of the README, explained why geometry is
  intentionally removed, and separated that semantic demonstration from the
  other four contract classes and the limited reactive lifecycle video.
- Added a hash-validated reactive AlpaSim rollout for NAVSIM EgoStatusMLP:
  197/197 finite outputs over 19.93 simulated seconds through live external
  driver, controller, and physics services.
- Added deterministic reconstruction of the public fixture's declared flat
  physics surface, a telemetry-recording seed-frame video-model server, raw
  camera-and-map run media, and a frozen-camera negative control.
- Added aggregate, validator, and regression gates for every retained reactive
  evidence hash and claim exclusion.
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
