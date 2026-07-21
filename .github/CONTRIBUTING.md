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

Install the pre-commit hook with `pre-commit install` when useful.

## Scope

Keep this branch focused on:

- AlpaSim simulator and external-driver adapters;
- launch, setup, readiness, batching, and reproduction tooling;
- packaged upstream override files and their provenance;
- run audits, summaries, support bundles, and bounded integration evidence;
- public tests and operator documentation.

Keep the public model presets aligned with the README:

- `constant_velocity`;
- `route_following`;
- `token_dagger_bc`;
- `direct_actor_planner`.

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
