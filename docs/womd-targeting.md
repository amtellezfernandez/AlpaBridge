# WOMD Targeting

WOD2Sim currently targets a WOD-style trajectory-policy interface on AlpaSim
scenes. It also provides one bounded Waymax experiment that loads the 20 WOMD
TFExamples bundled with a pinned upstream checkout. That experiment is a
semantic-contract study, not a general Waymax adapter, representative WOMD
benchmark, or WOMD-to-AlpaSim conversion. This guide separates those targets so
that an interface port is not mistaken for a dataset conversion.

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
| Actual WOMD records in the pinned route-contract study | Yes, bounded | Run `scripts/run_waymax_contract_study.sh`; it covers the bundled fixture, two deterministic policies, and one semantic mutation only. |
| Learned policy over a representative WOMD split | No | Use [Waymax](https://github.com/waymo-research/waymax) with licensed data and a pinned checkpoint, then map and validate the required WOD2Sim contracts. |
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

### Retained Route-Contract Study

The repository includes a narrow executable binding:

```bash
./scripts/run_waymax_contract_study.sh
```

It pins upstream commit
`a64dfec9be8576b60d9cecc94f406d9812d4a7d0`, verifies the bundled fixture
SHA-256, and writes:

- `artifacts/external/waymax_contract_study/scenario-results.jsonl`;
- `artifacts/external/waymax_contract_study/results-summary.json`;
- `artifacts/external/waymax_contract_study/manifest.json`.

The design holds Waymax state, dynamics, horizon, cadence, and non-SDC log
playback fixed while crossing route following and constant velocity with full
WOMD route geometry and an intervention-defined `KEEP_HEADING` geometric proxy.
The proxy command is generated by the experiment; it is not claimed as a field
read from the WOMD TFExample. The adapter computes the same route mutation for
constant velocity, whose declared signature ignores route.

This runner maps enough Waymax state, action, route provenance, and evidence to
test attribution correctness for the route semantic contract. It does not
implement general camera/actor observation mapping, learned-policy loading,
Waymax lifecycle services, or all five contracts.

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

This code is quoted as an upstream targeting pattern for broader data, not as
the retained fixture runner. Dataset version, split, storage path,
controlled-agent selection, and action construction must be pinned in the
experiment manifest.

A general WOD2Sim-to-Waymax binding would still need to map:

- Waymax simulator state and policy observations into the semantic contract;
- 10 Hz state/action timing into the temporal contract;
- reset, step, termination, and agent ownership into the lifecycle contract;
- WOMD access, versions, policy artifacts, and JAX dependencies into the
  deployment contract;
- scenario identifiers, inputs, actions, metrics, configuration, and hashes
  into the evidence contract.

Those mappings are not all present. Current cross-runtime evidence is limited
to the route semantic rule and its policy-dependency negative control.

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

The primary Waymax factorial experiment shows that replacing original route
geometry with a degraded proxy selectively changes a route-dependent policy
while leaving a route-independent policy exactly invariant. All arms complete,
but the contract gate rejects only the policy whose declared input requires the
lost geometry. This supports causal attribution correctness on the pinned
fixture, not route-following superiority, representative WOMD performance,
safety, or fault prevalence.

The AlpaSim route-loss media is a separate designed replay. It shows the same
policy-signature rule at an external-driver boundary, but its recorded future
observations are non-reactive. Together the two studies support bounded
cross-runtime applicability of one semantic contract, not generalization of all
five contracts.

## Official References

- [Waymo Open Motion Dataset format](https://waymo.com/open/data/motion/)
- [Waymo Open Dataset download and version history](https://waymo.com/open/download/)
- [Waymax repository and closed-loop examples](https://github.com/waymo-research/waymax)
- [Waymax research page](https://waymo.com/research/waymax/)
- [AlpaSim repository](https://github.com/NVlabs/alpasim)
- [AlpaSim runtime design](https://github.com/NVlabs/alpasim/blob/main/docs/DESIGN.md)
