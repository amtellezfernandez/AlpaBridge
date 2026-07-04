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

Run the focused bridge checks before opening a change:

```bash
make test
```

If you touch the paper:

```bash
make paper
```

For the full public verification path:

```bash
make verify
```

To remove generated local artifacts:

```bash
make clean
```

## Scope

Keep this repo focused on the WOD-to-AlpaSim bridge surface:

- simulator adapters
- launch/setup/readiness tooling
- patched-upstream AlpaSim integration files
- public-facing tests and docs

Avoid reintroducing unrelated research command surfaces from the larger private tree
unless they are required for the bridge release itself.
