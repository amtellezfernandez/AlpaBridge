# AlpaSim E2E Challenge Harness

This folder packages AlpaBridge's challenge-compatible external driver as a
hardened container. It is an integration harness, not a benchmark claim.

The image needs the official AlpaSim gRPC Python package as a build input. Keep
that code in an AlpaSim checkout and pass it as a Docker BuildKit named context;
do not vendor it into AlpaBridge.

## Policies

The driver serves whatever policy is selected via `--model`/`ALPABRIDGE_DRIVER_MODEL`,
behind the same gRPC service, session tracking, and telemetry regardless of
which one is running. Adding a new policy means registering it in
`src/alpabridge/driver/policy_registry.py`, not modifying the driver itself
- see that module for the extension point. This makes the harness usable for
policy research and benchmarking generally, not only for challenge submissions.

Built in: `constant_velocity`, `route_following`, `token_dagger_bc`,
`navsim_ego_status_mlp`, `vavam` (the public Valeo VideoActionModel -
`--checkpoint`/`--tokenizer-checkpoint`, or `ALPABRIDGE_DRIVER_CHECKPOINT`/
`ALPABRIDGE_DRIVER_TOKENIZER_CHECKPOINT`). `vavam` needs `torch` and the
public `vam` package (`pip install git+https://github.com/valeoai/VideoActionModel@v1.0.0`)
in the image - not covered by this folder's current slim Dockerfile, which
only targets the numpy-only policies. Its weights carry a research-only
license, separate from the code's MIT license - check that against your use
case before shipping a real submission.

## Build

```bash
ALPASIM_ROOT=/path/to/alpasim \
  bash integrations/alpasim_e2e_challenge/build_image.sh
```

The script expects:

```text
$ALPASIM_ROOT/src/grpc
```

Override with `ALPASIM_GRPC_ROOT=/path/to/src/grpc` if needed.

## Self-Test

The container can test the AlpaBridge adapter path without launching AlpaSim:

```bash
docker run --rm alpasim-e2e-alpabridge:latest \
  alpabridge-driver --self-test --model route_following
```

The output is JSON with `Drive` latency p50/p95, target misses, route source,
and an explicit `benchmark_result: false` field.

## Local Challenge-Style Driver

Start one read-only, tmpfs-backed driver:

```bash
bash integrations/alpasim_e2e_challenge/run_local_container.sh
```

Then run the official AlpaSim challenge dev preset from an AlpaSim challenge
checkout in another terminal:

```bash
ALPASIM_DRIVER_HOST=localhost ALPASIM_DRIVER_PORT=6789 \
  uv run alpasim_wizard +e2e_challenge=dev \
  wizard.log_dir=./runs/e2e_challenge_alpabridge_conformance
```

For NuPlan, use the challenge `+e2e_challenge_nuplan=dev` preset and provide
the required local NuPlan/MTGS data root.

## Evidence Boundary

This harness can produce external-driver compatibility evidence:

- the driver image starts under read-only root filesystem constraints;
- telemetry records `Drive` latency against the 100 ms control-tick target;
- route geometry reaches AlpaBridge's route-following contract;
- the local AlpaSim challenge dev preset can connect to the driver.

It is not policy-quality evidence until an actual local conformance run or
official submission returns metrics that are retained with provenance.

## Real Closed-Loop Rollout (vavam)

A full local closed-loop rollout was run against the `+e2e_challenge=dev`
preset with `vavam` (the real 318M-parameter public checkpoint, on a real
GPU) - not a self-test, not synthetic inputs. Result: the driver served all
197 `Drive` RPCs over the full 19.91s simulated scene with no protocol
errors or crashes. The vehicle tracked the route closely for the portion of
the rollout the eval kept (`dist_to_gt_trajectory` max 1.57m, stayed
on-road), then had a front collision partway through, after which the
eval's own modifiers stop scoring (`progress_rel_to_total: 0.41`).

That result supports two different claims, and it's worth keeping them
separate:

- **The integration works end to end**: the gRPC service, session
  handling, pose-aware inference caching, and image preprocessing all held
  up through a real rollout with no technical failures.
- **The policy itself is unevaluated**: one scene, one seed, a base
  checkpoint not fine-tuned or scored for driving quality here. The
  collision says something about this checkpoint on this scene, not about
  the harness.

Two real things were found and fixed only by running this for real, not by
synthetic testing:

- `resize_and_center_crop` (now in `image_ops.py`) scaled by height alone
  and only cropped width - correct only when the source is at least as wide
  as the target already. The real camera feed (568x320) is a hair narrower
  than VAVAM's 1600x900 target aspect ratio, so it failed on the very first
  real frame. Fixed to scale-to-cover (larger of both ratios) and crop both
  dimensions - this exact bug is also present in the official reference
  sample's own resize helper.
- Real measured latency (not modeled): on the tested GPU, cache hits
  (`PoseReanchoredInferenceCache`, see `inference_rate_cache.py`) are
  sub-millisecond; the periodic real-inference calls land around
  118-137ms - at or slightly over the challenge's stated 100ms/call
  figure. Without the cache, every one of the 197 calls would pay that
  cost; with it, only roughly 1 in 5 does. Whether the official evaluator
  scores per-call latency, an aggregate throughput budget, or something
  else isn't documented publicly - this describes what was measured, not a
  compliance claim.
