# AlpaSim E2E Challenge Compatibility

AlpaBridge can be used behind an AlpaSim E2E Challenge-style external-driver
interface, but this is an external-evaluator compatibility path, not a new
benchmark claim.

The official challenge submission unit is a Docker image that serves
`egodriver.EgodriverService`. The evaluator owns the simulator stack, scenes,
and leaderboard. AlpaBridge's role is narrower: reuse the route, sensor, timing,
lifecycle, deployment, and run-record checks inside that driver boundary.

## Ported Code

This deployment path is one consumer of AlpaBridge's general external driver
service, not challenge-specific code. The service and its policy extension
point live in:

```text
src/alpabridge/driver/driver_service.py
src/alpabridge/driver/policy_registry.py
```

Any policy registered in `policy_registry.py` is servable behind this
interface — built-ins include `constant_velocity`, `route_following`,
`mpc_planner`, `token_dagger_bc`, `navsim_ego_status_mlp`, and `vavam` (a
real published video-action policy, not a dependency-light baseline). The
driver itself reuses:

- `SensorFreshnessGuard`, trajectory validation, and resampling from the shared
  AlpaBridge adapter layer.
- Route-waypoint preservation and command-only fallback diagnostics from the
  AlpaBridge signal layer.

The module is importable without `alpasim_grpc` for unit tests. Running it as a
gRPC service requires the AlpaSim gRPC package from the AlpaSim challenge
checkout:

```bash
uv run alpabridge-driver --model route_following
```

## Intended Use

Use this path to test whether the AlpaBridge adapter survives a managed external
driver interface:

- `Drive` latency and 10 Hz response behavior.
- Multiple sessions and replicas.
- Route geometry reaching policy code instead of being reduced to a command.
- Read-only container root with writes restricted to `/tmp` or `/run`.
- No outbound network or mounted scene data inside the driver image.

## Container Harness

The runnable harness lives in:

```text
integrations/alpasim_e2e_challenge/
```

Build it from the AlpaBridge repo root while pointing to an AlpaSim challenge
checkout:

```bash
ALPASIM_ROOT=/path/to/alpasim \
  bash integrations/alpasim_e2e_challenge/build_image.sh
```

Run the adapter self-test inside the image:

```bash
docker run --rm alpasim-e2e-alpabridge:latest \
  alpabridge-driver --self-test
```

Start a local challenge-style driver container:

```bash
bash integrations/alpasim_e2e_challenge/run_local_container.sh
```

## Executed Example

Do not report this as an AlpaBridge benchmark result unless an actual challenge
submission or local challenge conformance run has completed and the returned
metrics are retained with provenance. Constant velocity and route following are
integration baselines, not competitive autonomous-driving policies.

The retained evidence under
`artifacts/external/alpasim_e2e_challenge_conformance/` records one completed
local external-evaluator run: 1/1 rollout completed,
197 driver RPCs were served, 396 image events were observed, and 197/197 driver
calls met the configured latency target. This is interface compatibility for
that pinned configuration, not a leaderboard or policy-quality result.

### A Second Run, With a Real Policy Instead of a Baseline

The run above uses `route_following`, a dependency-light baseline, so it
mainly proves the container and protocol boundary. A second local run swapped
in `vavam` — the public, published 318M-parameter Valeo VideoActionModel, on a
real GPU, with real downloaded weights — to check whether the same driver
holds up under an actual vision-conditioned policy instead of a stand-in.

Result: the driver served all 197 `Drive` RPCs over the full 19.91 s simulated
scene with no protocol errors or crashes. The vehicle tracked the route
closely for the portion of the rollout the eval kept
(`dist_to_gt_trajectory` max 1.57 m, stayed on-road), then had a front
collision partway through, after which the eval's own modifiers stop scoring
(`progress_rel_to_total: 0.41`). This run's metrics aren't retained under
`artifacts/` the way the baseline run's are, so treat the numbers as reported,
not as provenance-backed evidence.

That result supports two different claims, and they're worth keeping
separate:

- **The integration works end to end**: the gRPC service, session handling,
  pose-aware inference caching, and image preprocessing all held up through a
  real rollout with a real policy and no technical failures.
- **The policy itself is unevaluated**: one scene, one seed, a base
  checkpoint not fine-tuned or scored for driving quality here. The collision
  says something about this checkpoint on this scene, not about the harness.

Two real bugs were found and fixed only by running this for real, not by
synthetic testing:

- `resize_and_center_crop` (`src/alpabridge/simulator/image_ops.py`, general
  and not VAVAM-specific) originally scaled by height alone and only cropped
  width — correct only when the source is already at least as wide as the
  target. The real camera feed (568×320) is a hair narrower than VAVAM's
  1600×900 target aspect ratio, so it failed on the very first real frame.
  Fixed to scale-to-cover (the larger of both required ratios) and crop both
  dimensions. This exact bug is also present in the official reference
  sample's own resize helper.
- Real measured latency (not modeled): on the tested GPU, cache hits from
  `PoseReanchoredInferenceCache`
  (`src/alpabridge/simulator/inference_rate_cache.py`, also general-purpose —
  it exists because VAVAM's native 2 Hz doesn't match the driver's 10 Hz
  serving rate, not because of anything challenge-specific) are
  sub-millisecond; the periodic real-inference calls land around 118-137 ms —
  at or slightly over the challenge's stated 100 ms/call figure. Without the
  cache, every one of the 197 calls would pay that cost; with it, only
  roughly 1 in 5 does. Whether the official evaluator scores per-call
  latency, an aggregate throughput budget, or something else isn't documented
  publicly — this describes what was measured, not a compliance claim.


## ARM64: the blocker is the renderer, not the architecture

Investigated 2026-08-12 on NVIDIA GB10. Everything in the AlpaSim stack except one service
builds and runs natively on aarch64 — runtime, controller, physics, trafficsim, plugins and
grpc were verified inside a real 33.1GB ARM64 image (7/7 packages importing, `torch
2.13.0+cu130`, `torch.cuda.is_available()` true on GB10).

The single blocker is the **NuRec/sensorsim renderer**: `nvcr.io/nvidia/nre/nre-ga` publishes
a *single-arch* manifest (schema v2, amd64), not a manifest list, so there is no aarch64
image to run and nothing to rebuild — and under emulation it fails or stalls before opening
its gRPC port (the three abandoned `qemu-x86_64` containers found idling on the GB10 for 11
days were exactly this).

**AlpaSim ships a second renderer that does not have this problem.**
`runtime.renderer.kind=video_model` (OmniDreams, served via FlashDreams) replaces NuRec, and
per AlpaSim's `docs/VIDEO_MODEL.md` FlashDreams *"publishes Dockerfiles but not pre-built
images — we need to build them ourselves."* Built-from-source is precisely what makes an
ARM64 target possible, the same way AlpaBridge's own `local_checkout.patch` made
`alpasim-base` build on GB10. In `deploy=external_video_model` the renderer is an
`external_services` entry rather than a wizard-managed container, and `run_sim_services`
reduces to `[driver, physics, trafficsim, controller, runtime]` — all already verified on
aarch64.

Memory footprint favours the GB10 rather than working against it: the video-model path wants
48GB of VRAM for VaVAM (96GB for Alpamayo 1.5), which suits GB10 unified memory and rules out
a 16GB laptop GPU.

**Not yet attempted**, and the honest unknowns before it can be claimed: whether FlashDreams'
own Dockerfiles carry x86 assumptions (AlpaSim's did — four of them), the size of the model
checkpoint downloads, and disk headroom on the GB10. AlpaBridge also has no deploy config
combining an external driver with a video-model renderer; that config is the concrete next
piece of work.
