# Design

WOD-style trajectory policies and AlpaSim expose different contracts. Dataset
policies consume an assembled observation and return a fixed-horizon trajectory;
AlpaSim drivers participate in a long-lived message session and must return
trajectories at the simulator clock rate.

## Contract

WOD2Sim closes four gaps:

| Boundary | WOD2Sim behavior |
| --- | --- |
| Route | Preserves route waypoints alongside the high-level command. |
| Signal | Converts camera, ego-motion, route, and hazards into policy-facing state. |
| Output | Resamples policy trajectories and computes runtime headings. |
| Lifecycle | Isolates plugin discovery and handles late/repeated session messages safely. |

The package exposes two AlpaSim models:

- `token_dagger_bc`: a learned token policy requiring a compatible checkpoint.
- `direct_actor_planner`: a continuous candidate planner requiring an actor proxy.

Both use the same route/signal contract, sensor-freshness guard, trajectory
resampling, launch tooling, and evidence pipeline.

## AlpaSim Overrides

The tracked override layer under `src/wod2sim/alpasim_overrides/` extends the
AlpaSim checkout at the simulator boundary. `wod2sim-setup` validates the target
checkout before applying those files. WOD2Sim policy logic remains in the
package; third-party source remains clearly separated.

## Non-Goals

WOD2Sim is not a Waymo-to-AlpaSim scene converter, a simulator, or a new driving
policy. It does not redistribute datasets, scenes, checkpoints, or AlpaSim
binaries. Its contribution is the executable and auditable adapter contract.
