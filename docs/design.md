# Design

AlpaBridge connects short-horizon trajectory policies to AlpaSim's long-lived
external-driver service. The policy returns a local ego trajectory; AlpaSim
owns the downstream controller, physics, sensors, and next simulator state.

```text
AlpaSim messages
  -> session state
  -> policy observation
  -> trajectory policy
  -> output validation and resampling
  -> AlpaSim trajectory response
```

## Input Assembly

The driver receives camera images, ego motion, high-level commands, route
waypoints, and lifecycle messages over time. AlpaBridge:

- keeps each simulator session isolated;
- rejects messages that arrive in an invalid lifecycle state;
- retains route geometry separately from high-level route intent;
- tracks camera timestamps and content freshness;
- exposes only the inputs declared by the selected model adapter.

This policy-interface shape is not an official Waymo message format, and
using it does not imply that a WOMD scenario is running in AlpaSim.

### Camera Count Is Not Hardcoded

In plain terms: every rollout retained in this repo has one camera because
that's what the connected AlpaSim vehicle rig happens to have, not because
the adapter only knows how to handle one. Real self-driving rigs usually
point several cameras in different directions; the specific AlpaSim vehicle
setup connected here only has one, a single wide-angle camera facing
forward:

<p align="center">
  <img src="assets/readme/camera-rig-comparison.svg" alt="Left: a typical AV camera rig with eight labeled positions (front, front-left, front-right, side-left, side-right, rear-left, rear, rear-right), per Waymo's Perception-dataset camera schema. Right: this AlpaSim setup's actual rig, which only defines one forward-facing wide-angle camera." width="800">
</p>

This is a property of the connected AlpaSim vehicle's camera hardware, not
a limitation in the adapter. `alpabridge-doctor` checks a connected AlpaSim
setup for exactly this (see below), and the same adapter code supports
more cameras as soon as a rig with more of them is available. The rest of
this section is the technical detail.

`camera_ids` is a plain list, not a fixed slot: camera validation, per-camera
frame-count checks, and the sensor-freshness fingerprint (which combines a
CRC32 across every declared camera, not just the first) all iterate over
however many cameras a preset declares.
`tests/test_alpasim_integration.py::test_baseline_driver_accepts_more_than_one_camera`
and its two neighboring tests exercise the same `predict()` path with two
cameras, including that a frozen-camera rejection still fires when *both*
cameras stop advancing.

The presets shipped here declare one camera (`camera_front_wide_120fov`)
because that's the only camera the connected AlpaSim ego-vehicle rig
defines a mask for — checked directly against
`data/nre-artifacts/ego-hoods/hyperion_8` and `hyperion_8_1`, the two rig
configs referenced by every retained run's `ego_mask_rig_config_id`. This
is an AlpaSim ego-vehicle rig asset property, not a scene-specific or
adapter-specific limit: a different scene would use the same rig and
report the same one camera. Adding a genuinely multi-camera rig is an
upstream AlpaSim/NVIDIA asset question, outside what this repository can
fetch or configure.

`alpabridge-doctor` and `alpabridge-ready` cross-check every public preset's
declared cameras against whatever ego-hood rigs are present under the
connected `--alpasim-root`
(`_preflight_camera_rig_compatibility` in `run_alpasim_local_external.py`),
so a preset asking for a camera no local rig can provide fails loudly at
preflight time — before a live AlpaSim session — rather than failing deep
inside a running rollout. Skip it with `--skip-camera-rig-check` if needed.

## Model Presets

The dependency-light models are:

- `constant_velocity`: a straight-line smoke baseline;
- `route_following`: a waypoint-following baseline.

Optional models use the same external-driver boundary:

- `token_dagger_bc`: a learned token policy with a compatible local checkpoint;
- `direct_actor_planner`: a candidate planner with a scene-matched actor proxy.

The challenge-style driver also supports the public NAVSIM EgoStatusMLP
architecture for the retained integration run. It is not registered as a
general release-core preset because its checkpoint and framework dependencies
are external.

## Trajectory Conversion

Policy outputs are interpreted as ego-relative endpoint samples over a
five-second horizon. If the point count already matches
`round(output_frequency_hz * horizon_seconds)`, AlpaBridge returns the trajectory
unchanged. Otherwise it anchors interpolation at the current ego origin,
interpolates x/y positions onto the runtime endpoint grid, and recomputes
headings.

Outputs with non-finite coordinates, invalid shapes, or inconsistent timing are
rejected before they reach the AlpaSim controller.

## Setup And Runtime Checks

`alpabridge-setup` validates an AlpaSim checkout before applying the tracked
override files. `alpabridge-ready` checks platform, environment, Docker/GPU,
runtime image, model inputs, and selected scene assets. `alpabridge-launch` then
materializes the exact driver and simulator commands before optional execution.

Executed workflows retain expanded configuration, commands, provenance, driver
events, normalized audits, and summaries. Private checkpoints and gated scene
assets remain local.

## AlpaSim Overrides

The tracked override layer under `src/alpabridge/alpasim_overrides/` extends the
AlpaSim checkout at its plugin and route-message boundaries. The source copy
under `third_party/alpasim_overrides/` records provenance and modifications.
AlpaBridge policy logic remains in this package; AlpaSim itself is not vendored.

## Non-Goals

AlpaBridge is not:

- a simulator or controller replacement;
- a new autonomous-driving policy;
- a WOMD-to-AlpaSim scene converter;
- a source of AlpaSim scenes or learned checkpoints;
- a policy-performance benchmark.
