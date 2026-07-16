# Waymo Motion Dataset And AlpaSim

WOD2Sim is positioned between two different research surfaces:

- [Waymo Open Motion Dataset](https://waymo.com/open/data/motion/): logged
  multi-agent motion, maps, scenario protos, tensors, and public benchmarks.
- [NVIDIA AlpaSim](https://developer.nvidia.com/drive/simulation):
  a closed-loop AV simulation framework for testing policy decisions as
  scenarios unfold. The code is published at
  [NVlabs/alpasim](https://github.com/NVlabs/alpasim), with documentation at
  [nvlabs-alpasim.mintlify.app](https://nvlabs-alpasim.mintlify.app/introduction).

The repo is useful because those surfaces solve different problems. Waymo Motion
is strong for learning and benchmarking motion behavior from logged data.
AlpaSim is strong for policy-in-the-loop simulation. WOD2Sim is the adapter and
evidence layer between WOD-style policy outputs and AlpaSim execution.

## Waymo Open Motion Dataset

The Motion Dataset is published as sharded TFRecord files containing protocol
buffer data. It is split into 70% training, 15% testing, and 15% validation.

Core facts:

| Feature | Value |
| --- | --- |
| Dataset size | 103,354 segments |
| Original segment content | 20 seconds of object tracks at 10 Hz plus local map data |
| Model windows | 9 seconds: 1 second history and 8 seconds future |
| Training/validation samples | 10 history states, 1 current state, 80 future states, 91 total |
| Test samples | 10 history states plus 1 current state; future is hidden |
| Coordinate frame | Global frame: X east, Y north, Z up, meters |
| Formats | `Scenario` protocol buffers and tensorized `tf.Example` protos |
| Maps | Vector map features in Scenario protos; sampled points in tf.Example |

The official Motion page also points to benchmark tasks based on this dataset,
including the 2025 Interaction Prediction, Sim Agents, and Scenario Generation
challenges. Previous challenge tracks remain useful for comparing against older
baselines.

## What Is In The Scenario Proto

Each `Scenario` contains:

- `scenario_id`: unique scenario identifier.
- `timestamps_seconds`: timestamps for each step, starting at zero.
- `tracks`: object tracks, with type, dimensions, pose, velocity, heading, and
  validity flags over time.
- `dynamic_map_states`: traffic signal state over time.
- `map_features`: lane centers, lane boundaries, road boundaries, crosswalks,
  speed bumps, and stop signs.
- `sdc_track_index`: the self-driving car track index.
- `objects_of_interest`: objects selected as useful research behaviors.
- `tracks_to_predict`: selected objects for prediction in train/validation.
- `current_time_index`: the boundary between history and future.
- `compressed_frame_laser_data`: optional first-second lidar data in lidar
  splits.

Recent WOMD releases also add useful modalities and route features:

- v1.2.0 adds lidar points for the first second of each 9 second window.
- v1.2.1 adds camera tokens and embeddings for multiple camera views instead of
  raw images.
- v1.3.1 adds `sdc_paths`, including valid future route candidates for the SDC,
  enabling additional route-aware metrics.

## Why Waymo Motion Alone Is Not Enough Here

Waymo Motion is a dataset and benchmark suite. It does not, by itself, answer
whether a policy can survive closed-loop execution:

- It is log-derived; the scene does not change in response to a submitted policy.
- Test-set futures are hidden for challenge fairness, so public users cannot
  inspect closed-loop consequences there.
- Motion benchmarks measure forecast quality, not runtime integration, sensor
  freshness, driver process stability, support bundles, or AlpaSim controller
  behavior.
- The data is excellent for training and open-loop evaluation, but it is not a
  replacement for policy-in-the-loop simulation where the ego policy changes the
  rollout.

That gap is exactly where WOD2Sim fits: it takes WOD-style policy assumptions and
connects them to AlpaSim external-driver execution, then emits manifests, audits,
support bundles, and benchmark summaries.

## Why AlpaSim Matters

NVIDIA describes AlpaSim as an open-source AV simulation framework that combines
NuRec scenes, configurable traffic and policy models, and scalable closed-loop
testing. Its documentation describes it as a modular research simulator for
closed-loop end-to-end AV policy testing with realistic sensor data, vehicle
dynamics, and traffic scenarios.

For this repo, AlpaSim provides:

- closed-loop execution where the policy's decisions affect future observations;
- realistic sensor-facing runtime behavior;
- driver policy integration through an external-driver model surface;
- scalable scenario execution and reproducible run artifacts;
- a runtime where WOD2Sim can audit failures such as stale camera streams.

## WOD2Sim's Role

WOD2Sim does not replace Waymo Motion or AlpaSim. It connects them:

| Layer | What it provides |
| --- | --- |
| Waymo Motion | Logged trajectories, map context, prediction targets, benchmark framing |
| WOD2Sim | WOD-style signal reconstruction, public model adapters, launch/evidence CLI |
| AlpaSim | Closed-loop simulation, sensor/runtime behavior, rollout artifacts |

The practical output is not just a prediction tensor. The output is an evidence
packet:

- `closed-loop-reproduction-manifest.json`
- `run-audit.json`
- `support-bundle-report.json`
- `support-bundle.tar.gz` hash
- `wod2sim-benchmark-summary.json`

That is what makes the repo useful: it turns a WOD-style policy idea into an
auditable closed-loop run.

## Waymax In Context

Waymax is the closest paper-level comparison point: it is a data-driven,
accelerated simulator for large-scale autonomous driving research. WOD2Sim is
not a competing simulator; it is a bridge that turns WOD-style policy adapters
into auditable AlpaSim closed-loop evidence.

| Capability | Waymax | WOD2Sim |
| --- | --- | --- |
| Multi-agent closed-loop simulation | Yes | No |
| Accelerator-backed execution | JAX/XLA on GPU/TPU | CLI-driven evidence generation around AlpaSim runs |
| Real driving data | Waymo Open Motion Dataset scenarios | WOD-style adapters and benchmark inputs |
| Expert data playback | Logged trajectories and expert actors | Compact benchmark summaries and reproduction artifacts |
| Sim agents | Reactive rule-based and learned agents | Operator workflows, audits, and claim gating |
| Routes / goals | Route-conditioned planning inputs | Benchmark scopes, scene presets, and handoff guidance |
| Metrics | Route progress, off-road, collision, kinematic infeasibility, ADE | Claim-ready summaries, audits, manifests, and operator matrix |
| Sensor simulation | Out of scope | Out of scope |
| Training loop support | In-graph training and evaluation | Command rendering and evidence packaging |

Waymax is the simulator. WOD2Sim is the evidence layer.
