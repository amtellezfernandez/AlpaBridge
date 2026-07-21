# AlpaSim E2E Challenge Compatibility

AlpaBridge can be used behind an AlpaSim E2E Challenge-style external-driver
interface, but this is an external-evaluator compatibility path, not a new
benchmark claim.

The official challenge submission unit is a Docker image that serves
`egodriver.EgodriverService`. The evaluator owns the simulator stack, scenes,
and leaderboard. AlpaBridge's role is narrower: reuse the route, sensor, timing,
lifecycle, deployment, and run-record checks inside that driver boundary.

## Ported Code

The reusable adapter lives in:

```text
src/alpabridge/challenge/e2e_driver.py
```

It reuses:

- `ConstantVelocityAlpaSimModel` and `RouteFollowingAlpaSimModel` as
  dependency-light challenge drivers.
- `SensorFreshnessGuard`, trajectory validation, and resampling from the shared
  AlpaBridge adapter layer.
- Route-waypoint preservation and command-only fallback diagnostics from the
  AlpaBridge signal layer.

The module is importable without `alpasim_grpc` for unit tests. Running it as a
gRPC service requires the AlpaSim gRPC package from the AlpaSim challenge
checkout:

```bash
alpabridge-challenge-driver --model route_following
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
  alpabridge-challenge-driver --self-test
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
