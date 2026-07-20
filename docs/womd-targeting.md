# WOMD Targeting

WOD2Sim currently targets a WOD-style trajectory-policy interface on AlpaSim
scenes. It does not load Waymo Open Motion Dataset (WOMD) `Scenario` records,
convert WOMD maps or actors into AlpaSim assets, or provide a Waymax binding.
This guide separates those targets so that an interface port is not mistaken
for a dataset conversion.

## What WOMD Provides

The official [WOMD format documentation](https://waymo.com/open/data/motion/)
describes sharded TFRecords containing either `Scenario` protocol buffers or
tensorized `tf.Example` records. The corpus contains 103,354 20-second segments;
motion examples are 9-second windows with one second of history and eight
seconds of future at 10 Hz. A `Scenario` includes timestamped agent tracks, the
self-driving-car track index, vector-map features, and dynamic map state such as
traffic signals. Starting with WOMD 1.3.1, `sdc_paths` also provides candidate
future routes with positions, arc length, road-part identifiers, and on-route
metadata.

Those are logged scene records. AlpaSim's
[runtime design](https://github.com/NVlabs/alpasim/blob/main/docs/DESIGN.md)
instead sends live sensor and navigation inputs to a driver, receives a planned
trajectory, advances it through controller and physics, and feeds the updated
state into the next simulation step. Moving a policy or scene between the two
requires more than matching array shapes.

## Choose The Target

| Goal | Supported now? | Required work |
| --- | --- | --- |
| WOD-style policy interface on AlpaSim scenes | Yes | Use the existing WOD2Sim AlpaSim model, route, temporal, lifecycle, and evidence contracts. |
| Compatible learned trajectory policy on AlpaSim scenes | Partly | Supply a contract-compatible checkpoint and declare its exact input signature, coordinate frame, time base, and output sampling. |
| Actual WOMD scenario in a WOMD-native closed loop | No WOD2Sim binding | Use [Waymax](https://github.com/waymo-research/waymax), which includes a WOMD loader and closed-loop environment, then add WOD2Sim contracts only if cross-runtime validation is the experiment. |
| Actual WOMD scenario rendered and simulated by AlpaSim | No | Implement a licensed WOMD-to-AlpaSim scene converter and validate every semantic and temporal mapping below. |

Dataset provenance does not imply checkpoint compatibility. A model trained on
WOMD cannot be registered safely until its observations, actor selection,
history length, normalization, coordinate frame, route representation,
trajectory horizon, and sampling rate match a documented adapter.

## Target A Trajectory Policy At AlpaSim

1. Declare the policy signature. State whether it consumes camera, ego status,
   route geometry, a discrete command, actor history, vector maps, or some
   combination. Do not provide a field merely because it exists in AlpaSim.
2. Implement AlpaSim's trajectory-model boundary. The existing
   [`baseline_drivers.py`](../src/wod2sim/simulator/baseline_drivers.py) and
   [`alpasim_token_bc.py`](../src/wod2sim/simulator/alpasim_token_bc.py) show
   models that accept `PredictionInput` and return `ModelPrediction`.
3. Map the live inputs explicitly. WOD2Sim's AlpaSim override adds route
   waypoints to `PredictionInput`; the adapter also retains camera, command,
   ego-motion, session, and provenance data required by the selected policy.
4. Convert time and coordinates explicitly. Resample the policy horizon to the
   runtime contract, derive headings consistently, reject non-finite output,
   and record the source and target frame.
5. Register the model under the `alpasim.models` entry-point group and add a
   driver configuration. Add it to the curated `wod2sim-launch` model list only
   after its conformance and deployment checks pass.
6. Run setup, readiness, launch, and audit. A completed rollout is diagnostic
   evidence until the semantic, temporal, lifecycle, deployment, and evidence
   gates all pass.

The dependency-light route-following path can be materialized with:

```bash
wod2sim-setup --alpasim-root /path/to/alpasim
wod2sim-ready --alpasim-root /path/to/alpasim --scene-preset fresh_3scene
wod2sim-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model route_following \
  --scene-preset fresh_3scene
```

For the gated learned adapter:

```bash
wod2sim-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model token_dagger_bc \
  --checkpoint /path/to/contract-compatible-checkpoint.pt \
  --scene-preset fresh_3scene
```

`token_dagger_bc` names an adapter contract, not a claim that any arbitrary
published WOMD checkpoint is compatible. The retained known public learned
checkpoint in this repository is NAVSIM EgoStatusMLP seed 0; it is not
WOMD-trained and is intentionally reported as bounded lifecycle evidence.

## Run Actual WOMD Scenarios

For WOMD records, Waymax is the direct starting point. Its official repository
documents dataset access, `waymax.dataloader.simulator_state_generator(...)`,
and a closed-loop `BaseEnvironment`. This keeps WOMD tracks, maps, route
features, and dataset licensing at the native boundary.

First request WOMD access with the account that will read the dataset, install
the `gcloud` CLI, and authenticate that account:

```bash
gcloud auth login
gcloud auth application-default login
```

The upstream Waymax starting point is:

```python
from waymax import config, dataloader, dynamics, env

scenarios = dataloader.simulator_state_generator(
    config.WOD_1_1_0_TRAINING
)
waymax_env = env.BaseEnvironment(
    dynamics.InvertibleBicycleModel(),
    config.EnvironmentConfig(),
)
state = waymax_env.reset(next(scenarios))
```

This code is quoted as an upstream targeting pattern, not as an implemented
WOD2Sim adapter. Dataset version, split, storage path, controlled-agent
selection, and action construction must be pinned in the experiment manifest.

A future WOD2Sim-to-Waymax binding would need to map:

- Waymax simulator state and policy observations into the semantic contract;
- 10 Hz state/action timing into the temporal contract;
- reset, step, termination, and agent ownership into the lifecycle contract;
- WOMD access, versions, policy artifacts, and JAX dependencies into the
  deployment contract;
- scenario identifiers, inputs, actions, metrics, configuration, and hashes
  into the evidence contract.

That binding is not present, so cross-simulator transfer remains future work.

## Convert WOMD Scenes Into AlpaSim

Running a WOMD record inside AlpaSim is a separate scene-conversion project. A
credible converter would need, at minimum:

- license-compliant WOMD access and artifact provenance;
- global-to-simulator coordinate transforms and timestamp alignment;
- vector lanes, road boundaries, crosswalks, signs, and traffic-light state;
- selection and conversion of `sdc_paths` or another declared route source;
- ego and non-ego tracks with actor identity, validity, and dynamics policy;
- renderable camera or scene assets consistent with the source observations;
- controller and physics initialization consistent with the logged state;
- paired audits proving that route, actor, map, and timing semantics survive.

WOD2Sim does not implement that converter today. Therefore the supported claim
is "WOD-style trajectory policy running through AlpaSim's closed loop," not
"WOMD scenario running in AlpaSim."

## Evidence Boundary

The route-loss media in the README is a designed ablation. It proves that, for
the executed route-following policy and recorded messages, hiding geometry while
retaining a `LEFT` command changes the returned trajectory and triggers the
declared semantic contract. It does not estimate how often route loss occurs in
real integrations, compare WOD2Sim with another framework, or demonstrate
cross-simulator generalization.

## Official References

- [Waymo Open Motion Dataset format](https://waymo.com/open/data/motion/)
- [Waymo Open Dataset download and version history](https://waymo.com/open/download/)
- [Waymax repository and closed-loop examples](https://github.com/waymo-research/waymax)
- [Waymax research page](https://waymo.com/research/waymax/)
- [AlpaSim repository](https://github.com/NVlabs/alpasim)
- [AlpaSim runtime design](https://github.com/NVlabs/alpasim/blob/main/docs/DESIGN.md)
