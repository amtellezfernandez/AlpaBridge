# Contributing

## Development Setup

Recommended setup uses `uv`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

If you prefer standard tooling:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Local Verification

Run the test suite before opening a change:

```bash
make test
```

Run static checks with:

```bash
make lint
```

Run tests with the coverage gate with:

```bash
make coverage
```

Run the public release smoke check with:

```bash
make smoke
```

If you touch the paper:

```bash
make paper
```

If you touch contract-validation matrix (CVM) artifacts, public docs, claim
wording, or paper validation:

```bash
make cvm-check
make paper-verify
```

For the full public verification path:

```bash
make verify
```

Install pre-commit hooks if you want local Ruff checks before each commit:

```bash
pre-commit install
```

To remove generated local artifacts:

```bash
make clean
```

## Scope

Keep this repo focused on the WOD2Sim contract-validation integration surface:

- simulator adapters
- launch/setup/readiness tooling
- patched-upstream AlpaSim integration files
- evidence, audit, and claim-valid release artifacts
- public-facing tests, docs, and paper source

Keep the public CLI surface aligned with the release README:

- `constant_velocity`
- `route_following`
- `token_dagger_bc`
- `direct_actor_planner`

Avoid reintroducing unrelated research command surfaces unless they are required
for the public contract-validation release itself.

## Claim Boundary

Do not report an integration failure as a policy failure. A behavior row becomes
policy-attributable only after route, temporal, lifecycle, deployment, and
evidence checks pass and the aggregate marks it claim-valid. If a change touches
run summaries, paper text, plots, or README numbers, keep the integration failure
versus policy failure distinction explicit.

Do not commit restricted assets, private checkpoints, raw gated scene media,
tokens, credentials, private host paths, or support bundles that contain them.
Reference gated prerequisites by identifier or hash only.
