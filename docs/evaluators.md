# Evaluators

Which policy runs is one choice; which evaluator runs it is a separate,
independent choice. The standalone driver implements AlpaSim's own general,
versioned external-driver gRPC interface (`egodriver.EgodriverService`) —
not something built for any one evaluator — so anything that speaks it can
connect, the same way any policy in the [Policy
Backends](../README.md#policy-backends) table can be selected.

## Evaluation Paths

| Evaluator | What it is | Status |
| --- | --- | --- |
| Inside AlpaSim (`alpabridge-launch` / `alpabridge-reproduce`) | AlpaSim's own driver process loads your policy directly | Tested — see [Integration Test Results](../README.md#integration-test-results) |
| AlpaSim's local wizard, standalone driver | Any AlpaSim checkout's dev preset, pointed at a running `alpabridge-driver` | Tested — see [Integration Test Results](../README.md#integration-test-results) |
| AlpaSim E2E Challenge, standalone driver | NVIDIA's official hosted evaluator — same driver, packaged as a locked-down container | Tested locally — see [AlpaSim E2E compatibility](challenge-compatibility.md) |
| Your own evaluator, standalone driver | Any client speaking the same `egodriver.EgodriverService` interface | Tested — a plain gRPC client (not AlpaSim's wizard) drives one full session in [`tests/test_driver_grpc_client.py`](../tests/test_driver_grpc_client.py) |

The AlpaSim E2E Challenge is the one we've documented most, because it's
the one with a public, external leaderboard to point at — not because the
driver is built around it. A different evaluator speaking the same
protocol is exactly as supported as the Challenge is.

## Run As A Standalone Driver

The [main README](../README.md) covers running AlpaBridge inside AlpaSim
itself (`alpabridge-launch` / `alpabridge-reproduce`) — the simplest way to
try a policy. AlpaBridge can also run on its own, as a separate process. An
AlpaSim checkout (or any other evaluator) then connects to it over the
network (using gRPC). External evaluators use this path, since they only
know how to connect to an already-running driver, not how to load a plugin.
This skips the README's `Connect AlpaSim` step completely — AlpaSim just
points at the driver's address.

First, check that the driver works on its own — no AlpaSim checkout, GPU, or
checkpoint needed:

```bash
uv run alpabridge-driver --self-test --model route_following
```

To run the real loop, start the driver in one terminal:

```bash
uv run alpabridge-driver --model vavam \
  --checkpoint /path/to/vavam.ckpt \
  --tokenizer-checkpoint /path/to/tokenizer.jit
```

In a second terminal, point an AlpaSim checkout at the driver, using
AlpaSim's own local dev preset:

```bash
ALPASIM_DRIVER_HOST=localhost ALPASIM_DRIVER_PORT=6789 \
  uv run alpasim_wizard +e2e_challenge=dev
```

Any policy marked "standalone" in the [Policy
Backends](../README.md#policy-backends) table can be picked with `--model`
this way. `vavam` additionally needs
[`torch`](https://pytorch.org/get-started/locally/) (pick the build for
your hardware — CPU or a specific CUDA version) and the public `vam`
package:

```bash
pip install git+https://github.com/valeoai/VideoActionModel@v1.0.0
```

For a locked-down container built for the AlpaSim E2E Challenge's specific
submission format, see [AlpaSim E2E compatibility](challenge-compatibility.md).
