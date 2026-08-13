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



## Running on ARM64 (aarch64)

Closed-loop rollouts run on aarch64, using AlpaSim's video-model renderer instead of the
default NuRec/sensorsim one. This section is what a reader needs to reproduce that; it is not
a claim about driving quality (see the caveat at the end).

### Why the default renderer cannot be used

`nvcr.io/nvidia/nre/nre-ga` is published as a **single-arch amd64 manifest** — schema v2, not a
manifest list. There is no aarch64 image to run and, being prebuilt, nothing to rebuild. Under
emulation it fails or stalls before opening its gRPC port.

Every other service in the stack builds and runs natively on aarch64. Verified inside an ARM64
image on an NVIDIA GB10: `alpasim_controller`, `alpasim_runtime`, `alpasim_physics`,
`alpasim_grpc`, `alpasim_utils`, `alpasim_plugins` and `alpasim_eval` all import, with
`torch.cuda.is_available()` true. So the constraint is a renderer limitation, not an
architecture one.

`alpabridge-doctor` reflects this: `platform_compatibility` fails on aarch64 for the NuRec
deploy and passes for the video-model deploy.

### The ARM64 route: the video-model renderer

`runtime.renderer.kind=video_model` (OmniDreams, served via FlashDreams) replaces NuRec. It is
**built from source rather than pulled as a prebuilt image**, which is what makes an aarch64
target possible. Deployed as an external service, the wizard never needs an image for it at
all, so it can also live on another host.

AlpaBridge ships `deploy=local_external_driver_video_model` for this: both the policy and the
renderer are external, leaving the wizard managing `[physics, trafficsim, controller, runtime]`.

### Building the renderer image

FlashDreams publishes Dockerfiles but no prebuilt images. Its base Dockerfile is already
arch-clean: a multi-arch CUDA base, an arch-neutral apt set, multi-arch `uv`, and an AWS CLI
step that branches on `aarch64`. It installs no Python dependencies; `docker/Dockerfile.alpasim`
does that in one `uv sync --locked`.

Two things need fixing first:

**`Dockerfile.alpasim` does not copy the `apps/` workspace member.** `pyproject.toml` declares
members `flashdreams`, `integrations/*` and `apps/*`, but only the first two are copied, so
`apps/t2v_demo` is absent, the container resolves one fewer package than the lockfile pins, and
`uv sync --locked` fails with *"the lockfile needs updating"*. This is not
architecture-specific — it fails the same way on x86_64, with the pristine lockfile — and it is
fixed by one line:

```dockerfile
COPY apps ./apps
```

**The base image tag is inconsistent between projects.** AlpaSim's `docs/VIDEO_MODEL.md` builds
the base as `flashdreams-base:local`, while FlashDreams' own README and `Dockerfile.alpasim`'s
`ARG FLASHDREAMS_BASE_IMAGE` default both use `flashdreams:local`. Pick one, or pass
`--build-arg FLASHDREAMS_BASE_IMAGE=<tag>` explicitly.

Separately, `transformer-engine-cu13` is pinned at a version whose only wheel is
`manylinux_2_28_x86_64`, with no sdist. It does not affect this build, because
`transformer-engine` sits behind a `dev` extra that `uv sync --package flashdreams-omnidreams`
does not install — but it will block anyone resolving that extra on aarch64. Adjacent patch
releases do publish aarch64 wheels and the project only requires a lower bound, so the pin is a
lockfile artifact rather than a constraint.

### Fetching the model weights

The weights are gated on Hugging Face (`gated: auto`); the account must accept the model's terms
before the download will succeed. An unaccepted account gets `403` on the artifact while the
repository's metadata endpoint still returns `200`, so check the artifact itself, not the repo.

**Download the weights on the host rather than letting the container do it.** In-container
downloads have been observed to stall partway through a multi-GB file with no further log
output. A host-side `hf download` resumes and completes. If a container has already written to
the shared cache, it will own those paths as root; where there is no passwordless sudo, Docker
itself is the way to hand them back:

```bash
docker run --rm -v "$HOME/.cache/huggingface:/hf" <image> \
  chown -R "$(id -u):$(id -g)" /hf/hub/models--<org>--<repo>
```

### Running a rollout

Start the renderer, then launch. Both must agree on the camera count and the chunk size:

```bash
docker run --rm --gpus all --network host --name fd-server \
  -e HF_TOKEN="$(cat ~/.cache/huggingface/token)" \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  flashdreams-alpasim:local \
  /opt/flashdreams/bin/torchrun --standalone --nnodes=1 --nproc_per_node=1 \
  -m omnidreams.grpc.server \
  --pipeline_config_name omnidreams-sv-2steps-chunk2-loc6-lightvae-lighttae-perf \
  --host 0.0.0.0 --port 50051 --output_format jpeg --jpeg_quality 90

ALPABRIDGE_ALPASIM_DEPLOY_TARGET=local_external_driver_video_model \
alpabridge-launch --mode both --model constant_velocity --scene-id <scene> \
  --wizard-arg '+chunking=8frame' \
  --wizard-arg '+cameras=1cam' \
  --wizard-arg 'wizard.external_services.renderer=[localhost:50051]'
```

Four requirements are easy to miss:

- **The camera rig must equal the renderer's view count.** AlpaSim's video-model documentation
  says not to inject a `+cameras=` override, because the rig and calibration come from the
  recorded USDZ seed frames. Read literally that fails immediately: AlpaSim's runtime defaults
  to a 2-camera rig while a single-view server (`omnidreams-sv-…`) expects one, and the session
  dies on the first render call with `Expected 1 camera names, got 2` before producing a frame.
  Pin the rig to the server's view count — `1cam` for a single-view pipeline, or run an
  `omnidreams-mv-…` pipeline and pin a rig matching it.
- **`+chunking=<n>frame` is mandatory** and must match the server's `--num_frames_per_block`.
  The preset keeps `chunk_frames`/`first_chunk_frames` aligned with `control_timestep_us` and
  `force_gt_duration_us`; those are a matched set, since `first_chunk_frames` is constrained by
  the server's VAE temporal compression ratio.
- **AlpaBridge must be installed into the AlpaSim virtualenv**, not only the host one, or the
  wizard cannot discover its Hydra config provider and fails with
  `Could not find 'driver/<model>'`. `alpabridge-setup` does this; a hand-rolled venv does not.
- **One server serves one rollout session at a time.** The renderer is stateful by design — it
  opens a session, then generates video in chunks — so a multi-scene batch pointed at a single
  server fails every session but the active one with `Session not found: <uuid>`. Run one scene
  per invocation, or scale renderer replicas.
  `runtime.endpoints.renderer.n_concurrent_rollouts` describes the server's capacity; it does
  not serialise a batch.

### Scene assets need calibration data

The video-model renderer parses camera intrinsics and rig-to-camera calibration out of the USDZ,
so an asset that lacks them cannot be used with it:

```
FileNotFoundError: clipgt/calibration_estimate.parquet not found in .../<uuid>.usdz
```

Assets vary on this: some carry a full `clipgt/*.parquet` set (`calibration_estimate`,
`egomotion_estimate`, `lane`, `traffic_light`, …) and some carry none. An asset without them
still works under NuRec, which renders directly and needs no such conditioning. Check before
assuming a scene preset is usable here:

```bash
unzip -l <scene>.usdz | grep calibration_estimate.parquet
```

### Verified result

On an NVIDIA GB10 (aarch64), with camera frames generated by the video model on that host:

```
Session COMPLETED — simulated 19.82 sim seconds in 536.32s wall clock (0.04x real time)
aggregate_status: completed   wizard_returncode: 0
frames: 73   sensor pipeline ok: True   sensor failures: 0   result counts: {'ok': 73}
```

`alpabridge-doctor` reports `alpasim environment: valid` for this deploy on that host.

**Caveat.** 22 of those 73 frames reported `route_source=command_proxy` rather than
`alpasim_waypoints`, so `alpabridge-audit-run` classes the run as adapter triage rather than
claim-valid evidence. The same pattern appears on x86_64, so it is not architecture-related.
This demonstrates the deployment path, not driving quality.
