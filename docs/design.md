# Design

WOD-style trajectory policies and AlpaSim expose different contracts. Dataset
policies consume an assembled observation and return a fixed-horizon trajectory;
AlpaSim drivers participate in a long-lived message session and must return
trajectories at the simulator clock rate.

In this repository, WOD-style describes the policy interface shape: logged
observations, route intent or route geometry, and short-horizon ego-relative
trajectory outputs. It is not a claim of official Waymo challenge compatibility,
leaderboard submission support, or complete Waymo scene reconstruction inside
AlpaSim.

## Five Contracts

WOD2Sim closes five integration gaps:

| Contract | WOD2Sim behavior |
| --- | --- |
| Semantic | Preserves route waypoints, camera/ego-motion signals, and structured hazards as policy-facing state. |
| Temporal | Resamples policy trajectories to the simulator runtime grid and recomputes headings. |
| Lifecycle | Isolates plugin discovery and handles late/repeated session messages safely. |
| Deployment | Materializes commands, topology, runtime preconditions, hashes, and launch provenance. |
| Evidence | Requires audits, manifests, support-bundle status, and retained denominators before claims. |

The package exposes four AlpaSim models:

- `constant_velocity`: a dependency-light straight-line baseline requiring no private artifact.
- `route_following`: a dependency-light waypoint-following baseline requiring no private artifact.
- `token_dagger_bc`: a learned token policy requiring a compatible checkpoint.
- `direct_actor_planner`: a continuous candidate planner requiring an actor proxy.

All four use the same route/signal contract, sensor-freshness guard, trajectory
resampling, launch tooling, and evidence pipeline.

## Trajectory Resampling

WOD-style policy outputs are interpreted as ego-relative endpoint samples over a
five-second horizon. If the policy point count already matches
`round(output_frequency_hz * horizon_seconds)`, WOD2Sim returns the trajectory
unchanged. Otherwise, the adapter anchors interpolation at the current ego
origin `(0, 0)` and linearly interpolates x/y positions onto the simulator
runtime endpoint grid. Headings are recomputed from adjacent runtime points using
the same AlpaSim trajectory-model helper used by the adapters.

The contract tests assert exact identity for native runtime samples and exact
linear interpolation, within `float32` tolerance, for straight endpoint
trajectories. Curved trajectories inherit ordinary piecewise-linear
interpolation error from the policy sample spacing; this release does not claim
a closed-loop accuracy bound from resampling alone.

## AlpaSim Overrides

The tracked override layer under `src/wod2sim/alpasim_overrides/` extends the
AlpaSim checkout at the simulator boundary. `wod2sim-setup` validates the target
checkout before applying those files. WOD2Sim policy logic remains in the
package; third-party source remains clearly separated.

## Non-Goals

WOD2Sim is not a Waymo-to-AlpaSim scene converter, a simulator, or a new driving
policy. It does not redistribute datasets, scenes, checkpoints, or AlpaSim
binaries. Its contribution is an executable and auditable system-integration
contract.
