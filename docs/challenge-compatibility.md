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
