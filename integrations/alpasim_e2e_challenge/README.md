# AlpaSim E2E Challenge Harness

This folder packages WOD2Sim's challenge-compatible external driver as a
hardened container. It is an integration harness, not a benchmark claim.

The image needs the official AlpaSim gRPC Python package as a build input. Keep
that code in an AlpaSim checkout and pass it as a Docker BuildKit named context;
do not vendor it into WOD2Sim.

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

The container can test the WOD2Sim adapter path without launching AlpaSim:

```bash
docker run --rm alpasim-e2e-wod2sim:latest \
  wod2sim-challenge-driver --self-test --model route_following
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
  wizard.log_dir=./runs/e2e_challenge_wod2sim_smoke
```

For NuPlan, use the challenge `+e2e_challenge_nuplan=dev` preset and provide
the required local NuPlan/MTGS data root.

## Evidence Boundary

This harness can produce external-driver compatibility evidence:

- the driver image starts under read-only root filesystem constraints;
- telemetry records `Drive` latency against the 100 ms control-tick target;
- route geometry reaches WOD2Sim's route-following contract;
- the local AlpaSim challenge dev preset can connect to the driver.

It is not policy-quality evidence until an actual local smoke run or official
submission returns metrics that are retained with provenance.
