# Bring Your Own Policy

Implement the contract. Here's the required shape, in outline:

```python
from alpabridge.simulator.alpasim_contract import BaseTrajectoryModel, ModelPrediction

class MyPolicy(BaseTrajectoryModel):
    camera_ids = ["camera_front_wide_120fov"]
    context_length = 1
    output_frequency_hz = 4

    @classmethod
    def from_config(cls, model_cfg, device, camera_ids, context_length, output_frequency_hz):
        return cls()  # load your checkpoint here

    def _encode_command(self, command):
        ...  # map DriveCommand to whatever your policy expects

    def predict(self, prediction_input) -> ModelPrediction:
        trajectory_xy = ...  # your model's output, an (N, 2) array
        headings = ...       # heading at each point; see baseline_drivers.py for one way
        return ModelPrediction(trajectory_xy=trajectory_xy, headings=headings)
```

## Slow Inference?

If your real forward pass can't keep up with how often the driver calls
`predict` — the exact problem `vavam` has, since its native rate is 2 Hz
against the driver's 10 Hz — reuse the same throttling cache instead of
writing your own pose-tracking logic:

```python
from alpabridge.simulator.inference_rate_cache import PoseReanchoredInferenceCache

class MyPolicy(BaseTrajectoryModel):
    def __init__(self):
        self._inference_cache = PoseReanchoredInferenceCache(min_interval_s=0.5)  # your model's real cadence

    def predict(self, prediction_input) -> ModelPrediction:
        def _infer():
            return self._run_real_forward_pass(prediction_input)  # your heavy model call, an (N, 2) array

        trajectory_xy, was_cached = self._inference_cache.get(prediction_input, _infer)
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        return ModelPrediction(trajectory_xy=trajectory_xy, headings=headings)
```

`_infer()` only runs when the cache is empty or older than `min_interval_s`;
otherwise the cache reprojects the last real prediction onto the car's
*current* position instead of replaying it unchanged. It's a general
building block, not vavam-specific — see
[`inference_rate_cache.py`](../src/alpabridge/simulator/inference_rate_cache.py)
for the reprojection math, and
[`vavam_model.py`](../src/alpabridge/simulator/vavam_model.py) for the real,
tested usage this pattern is based on.

## Register It

Matching the [Policy Backends](../README.md#policy-backends) table:

- **Inside AlpaSim**: declare an `alpasim.models` entry point — the same
  mechanism the built-in policies marked "Inside AlpaSim" use (see
  `pyproject.toml`'s `[project.entry-points."alpasim.models"]`). Entry-point
  groups are a standard Python packaging mechanism, discovered across every
  installed package, not just one — so this can live in your own package
  alongside AlpaBridge, not inside a fork of it.
- **Standalone driver**: add one
  `register_policy(DriverPolicy("my_policy", my_factory))` call in
  [`policy_registry.py`](../src/alpabridge/driver/policy_registry.py). As of
  today this means changing this repo — see
  [Contributing](../.github/CONTRIBUTING.md) — there's no external plugin
  hook for this path yet.

Either way, nothing about the serving code itself (timing, retries,
evidence capture, the gRPC service) changes — that's the same for every
policy in the [Policy Backends](../README.md#policy-backends) table,
including a future vision-language or world-model one.

Once registered for the standalone driver (see
[Evaluators](evaluators.md)), test it the same way as any built-in:

```bash
uv run alpabridge-driver --self-test --model my_policy
```
