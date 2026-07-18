# AlpaSim E2E Challenge Compatibility

WOD2Sim can be used behind an AlpaSim E2E Challenge-style external-driver
interface, but this is an external-evaluator compatibility path, not a new
benchmark claim.

The official challenge submission unit is a Docker image that serves
`egodriver.EgodriverService`. The evaluator owns the simulator stack, scenes,
and leaderboard. WOD2Sim's useful role is narrower: reuse the route, sensor,
temporal, lifecycle, deployment, and evidence contracts inside that driver
boundary so a score is not interpreted before the integration path is valid.

## Ported Code

The reusable adapter lives in:

```text
src/wod2sim/challenge/e2e_driver.py
```

It reuses:

- `ConstantVelocityAlpaSimModel` and `RouteFollowingAlpaSimModel` as
  dependency-light challenge drivers.
- `SensorFreshnessGuard`, trajectory validation, and resampling from the shared
  WOD2Sim contract layer.
- Route-waypoint preservation and command-only fallback diagnostics from the
  WOD2Sim signal layer.

The module is importable without `alpasim_grpc` for unit tests. Running it as a
gRPC service requires the AlpaSim gRPC package from the AlpaSim challenge
checkout:

```bash
python -m wod2sim.challenge.e2e_driver --model route_following
```

## Intended Use

Use this path to test whether WOD2Sim contracts survive a managed external
driver interface:

- `Drive` latency and 10 Hz response behavior.
- Multiple sessions and replicas.
- Route geometry reaching policy code instead of being reduced to a command.
- Read-only container root with writes restricted to `/tmp` or `/run`.
- No outbound network or mounted scene data inside the driver image.

## Non-Claim

Do not report this as a WOD2Sim benchmark result unless an actual challenge
submission or local challenge smoke run has completed and the returned metrics
are retained with provenance. Constant velocity and route following are
integration baselines, not competitive autonomous-driving policies.

For the paper, this remains future/external validation. The central result stays
the separation between integration-invalid rows and policy-attributable
behavior.
