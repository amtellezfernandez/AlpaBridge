# Simulator Surface

This subtree is the internal simulation/debug stack of the repo.

It is **not** a public benchmark leaderboard surface. Do not treat its pass rates, COMPASS scores, or
GIF rollouts as paper evidence for realistic autonomous driving. Its role is to exercise
policy logic, produce local visual debugging artifacts, and support AlpaSim adapter code.

Use it for:

- Spotlight Reflex policy logic
- debug scenario generation
- simulator step/update rules for local development
- COMPASS-style internal checks
- first-party AlpaSim integration adapters
- simulator-scoped patched-upstream AlpaSim work

## Start Here

- `spotlight_reflex.py` — primary geometry-first driving policy
- `environment.py` — simulator loop and rollout execution
- `compositional_scenarios.py` — long-tail scenario generation
- `wod_scenarios.py` — WOD-style scenario families
- `compass.py` — simulator benchmark scoring

## File Map

- `perception.py` — obstacle / route state extraction
- `world_model.py` — simulator-visible state bundle
- `planner.py` / `policy.py` — maneuver planning interfaces
- `trajectory_selector.py` — candidate scoring / ranking in the simulator tier
- `safety.py` — safety filters and penalties
- `render.py` — visual rendering utilities
- `certification.py` — readiness and constraint checks
- `interaction_features.py` — interaction-derived simulator features

## AlpaSim Lives Inside This Stack

These files are still first-party repo code:

- `alpasim_signal.py`
- `alpasim_spotlight.py`
- `alpasim_token_bc.py`
- `alpasim_direct_actor_planner.py`

Reason:
they are adapters from this repo's policy surface into AlpaSim execution, not vendored
AlpaSim source.

The simulator-scoped patched-upstream boundary is:

- [`third_party/alpasim_overrides/README.md`](../../../third_party/alpasim_overrides/README.md)

Treat that directory as part of the simulation audit surface, not as a separate
top-level subsystem. It contains upstream-derived AlpaSim work that was materially
modified for this project.

If you need the simulator write-up, go to:

- [`docs/simulation.md`](../../../docs/simulation.md)
