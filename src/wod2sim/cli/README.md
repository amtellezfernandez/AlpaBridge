# CLI Surface

This subtree owns command entrypoints and orchestration code.

Rules:

- `scripts/` stays as thin executable wrappers only
- command implementations live under `src/wod2sim/cli/commands/`
- reusable library logic belongs in `model/`, `simulator/`, or `neutral/`, not in wrappers

If a command grows domain logic, move that logic down into the owning package and keep
the command module as argument parsing plus orchestration.
