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

### Building the video-model renderer for ARM64: what to know before you start

Checked 2026-08-12 against `NVIDIA/flashdreams` @ `ac214dd`, read-only, before committing to
a build. The Dockerfiles themselves are close to arch-clean — far cleaner than AlpaSim's
were:

- `docker/Dockerfile` builds `FROM nvidia/cuda:13.2.1-cudnn-devel-ubuntu24.04`, which
  publishes **both** amd64 and arm64 manifests.
- Its apt set is arch-neutral, `uv` comes from a multi-arch image, and the AWS CLI step
  already branches `x86_64` / `aarch64` explicitly.
- It installs no Python dependencies at all; `docker/Dockerfile.alpasim` does that with a
  single `uv sync --locked --package flashdreams-omnidreams --no-editable`.

So the entire ARM64 question reduces to what `uv sync --locked` does inside the container.

**The blocker turned out to be architecture-independent, and it is an upstream bug.** The
build fails at `uv sync --locked` with *"the lockfile needs updating"* — the container
resolves **255** packages against a **256**-package lock. Cause: `pyproject.toml` declares
workspace members `flashdreams`, `integrations/*` and **`apps/*`**, but `Dockerfile.alpasim`
copies only the first two, so `apps/t2v_demo` is missing and the workspace no longer matches
the lock. One line fixes it:

```dockerfile
COPY apps ./apps
```

Verified this is not arch-specific and not self-inflicted: the *pristine, unmodified* lock
fails the same way with the same 255/256 counts, and once `apps/` is copied the pristine lock
builds cleanly on aarch64. Nothing else was needed. This is worth reporting to FlashDreams —
`Dockerfile.alpasim` is broken as shipped at `ac214dd` on any architecture.

**A separate latent ARM issue, not on this path.** `transformer-engine-cu13` is pinned at
`2.17.0`, which is wheel-only and x86_64-only with no sdist. It does *not* block this build,
because `transformer-engine` sits behind a `dev` extra that
`uv sync --package flashdreams-omnidreams` never installs — an earlier revision of this note
claimed it was the blocker, which was wrong. It would bite anyone resolving the dev extra on
aarch64, and it is trivially avoidable: that package ships aarch64 wheels for nearly every
release, `2.17.0` is one of only two recent versions missing one, `2.17.1` has one, and
`pyproject` only requires `>=2.12`. Worth proposing upstream, but as a latent fix rather than
a build blocker.

**Second trap, cross-repo:** AlpaSim's `docs/VIDEO_MODEL.md` says to build the base as
`-t flashdreams-base:local`, but `Dockerfile.alpasim` declares
`ARG FLASHDREAMS_BASE_IMAGE=flashdreams:local` and FlashDreams' own `docker/README.md` uses
`flashdreams:local`. Follow AlpaSim's instructions verbatim and the second build looks for an
image that does not exist. Either tag the base `flashdreams:local`, or pass
`--build-arg FLASHDREAMS_BASE_IMAGE=flashdreams-base:local`.

### End-to-end ARM64 status: everything technical works; the gate is model access

Attempted on GB10 (2026-08-13). The OmniDreams gRPC server starts from the ARM64 image and
gets all the way to fetching weights — torch, CUDA and the `omnidreams` package all load on
aarch64, with no architecture error anywhere in the traceback. It then stops here:

```
httpx.HTTPStatusError: Client error '403 Forbidden' for url
'https://huggingface.co/nvidia/omni-dreams-models/resolve/main/single_view/2b_res720p_30fps_i2v_hdmap_distilled.pt'
```

`nvidia/omni-dreams-models` is `gated: auto`. Measured from the GB10: the artifact returns
**403 with** the host's HF token and **401 without** it, while the repo's metadata API returns
200 either way. So the token is valid and being sent — the account simply has not been
granted the gate. That is a licence acceptance on huggingface.co for the account whose token
is in `~/.cache/huggingface/token`, and nothing in this repo can substitute for it.

Everything up to that point is verified working on aarch64:

| step | state |
| --- | --- |
| `flashdreams-base:local` (9.15GB) | built |
| `flashdreams-alpasim:local` (15GB) | built; `torch 2.12.1+cu130`, CUDA true on GB10 |
| AlpaSim host venv incl. `alpasim_driver`/`vam`/`lightning` | installs on aarch64 |
| `alpabridge-doctor` `platform_compatibility` | `ok` for the video-model deploy, `failed` for NuRec |
| OmniDreams server import + CUDA init | reaches weight download |
| model weights | **blocked: HF gate not granted** |

**A gap the attempt exposed in this deploy config**, now documented in the config itself: it
is incomplete without a chunking preset (`--wizard-arg '+chunking=8frame'`). The video model
generates in blocks, and the preset keeps `chunk_frames`/`first_chunk_frames` aligned with
`control_timestep_us` and `force_gt_duration_us`. Those are a matched set — `first_chunk_frames`
is constrained by the server's VAE temporal compression ratio of 4 — and the right values
depend on the `--num_frames_per_block` the server was started with, so they are deliberately
not inlined.

### ARM64 end to end: achieved

A full closed-loop AlpaSim rollout ran on an NVIDIA GB10 (aarch64) on 2026-08-13, with camera
frames generated by the OmniDreams video world model running natively on that host:

```
Session COMPLETED: scene=clipgt-90d1908c-... simulated 19.82 sim seconds in 536.32s (0.04x real time)
aggregate_status: completed | wizard_returncode: 0
frames: 73 | sensor pipeline ok: True | sensor failures: 0 | result counts: {'ok': 73}
```

The working invocation:

```bash
ALPABRIDGE_ALPASIM_DEPLOY_TARGET=local_external_driver_video_model \
alpabridge-launch --mode both --model constant_velocity --scene-id <scene> \
  --wizard-arg '+chunking=8frame' \
  --wizard-arg '+cameras=1cam' \
  --wizard-arg 'wizard.external_services.renderer=[localhost:50051]'
```

with the renderer started from the ARM64 image:

```bash
docker run --rm --gpus all --network host --name fd-server \
  -e HF_TOKEN="$(cat ~/.cache/huggingface/token)" \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  flashdreams-alpasim:local \
  /opt/flashdreams/bin/torchrun --standalone --nnodes=1 --nproc_per_node=1 \
  -m omnidreams.grpc.server \
  --pipeline_config_name omnidreams-sv-2steps-chunk2-loc6-lightvae-lighttae-perf \
  --host 0.0.0.0 --port 50051 --output_format jpeg --jpeg_quality 90
```

Four things had to be fixed that no amount of reading would have found:

1. **The weight download stalls inside the container** (stuck at 67MB of 4.1GB, no log movement).
   Fetch host-side with `hf download`, which resumes. That first needs the cache chowned back:
   the container writes it as root, and with no passwordless sudo on the host, Docker itself is
   the escalation (`docker run --rm -v ~/.cache/huggingface:/hf <image> chown -R uid:gid /hf/...`).
2. **AlpaBridge must be installed into the *AlpaSim* venv**, not just the host venv, or the
   wizard cannot discover its Hydra config provider and fails with
   `Could not find 'driver/constant_velocity'`. `alpabridge-setup` does this; a hand-rolled
   venv bootstrap does not.
3. **The camera rig must equal the renderer's view count** — see the deploy config. The docs'
   "do not inject `+cameras=`" is wrong as stated for a single-view server.
4. **`+chunking=<n>frame` is mandatory**, and must match the server's `--num_frames_per_block`.

**Caveat on the result:** 22 of 73 frames reported `route_source=command_proxy` rather than
`alpasim_waypoints`, so `alpabridge-audit-run` classes this as adapter triage, not claim-valid
evidence. The same pattern appears on x86, so it is not ARM-specific, but this run demonstrates
the deployment path rather than driving quality.
