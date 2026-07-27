# Contributing

## Development Setup

Recommended setup uses `uv`:

```bash
uv sync --extra dev
```

With standard tooling:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Verification

Run the full public release path before opening a change:

```bash
make verify
```

Focused targets are also available:

```bash
make lint
make test
make conformance
make coverage
make smoke
make build
```

`make test` runs the full test suite (294 tests as of this writing) and
needs no AlpaSim checkout, GPU, or checkpoint. `make verify` adds Ruff, a
coverage check, a fresh-checkout install, and a wheel/sdist build. CI runs
the same steps on every push, plus an install-from-wheel smoke test that
exercises the real console-script entry points.

Install the pre-commit hook with `pre-commit install` when useful.

## Scope

Keep this branch focused on:

- AlpaSim simulator and external-driver adapters;
- launch, setup, readiness, batching, and reproduction tooling;
- packaged upstream override files and their provenance;
- run audits, summaries, support bundles, and bounded integration evidence;
- public tests and operator documentation.

Keep the `pyproject.toml` `alpasim.models` entry points aligned with the
README's [Policy Backends](../README.md#policy-backends) table:

- `constant_velocity`;
- `route_following`;
- `token_dagger_bc`;
- `direct_actor_planner`.

Standalone-driver-only policies (`navsim_ego_status_mlp`, `vavam`, and any
new ones) go in
[`src/alpabridge/driver/policy_registry.py`](../src/alpabridge/driver/policy_registry.py)
instead — see [Bring Your Own Policy](../docs/custom-policies.md) for which
serving path a new policy needs.

Do not add a dataset claim merely because a policy interface resembles WOMD.
Actual WOMD execution and WOMD-to-AlpaSim scene conversion require separate
implementations and validation.

Do not commit restricted assets, private checkpoints, raw gated scene media,
tokens, credentials, private host paths, or unredacted support bundles.

## Good First Contribution: A New Dataset Or Checkpoint Preset

The adapter contract is dataset-agnostic, but only a handful of presets are
implemented. See [compatible datasets and checkpoints](../docs/womd-targeting.md)
for datasets that would fit (nuScenes, nuPlan, Argoverse 2, or your own logs)
and what wiring one up requires.
