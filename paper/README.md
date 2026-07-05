# Paper

This directory contains the LaTeX source for:

`WOD2Sim: Adapting WOD-Style Driving Policies to Closed-Loop AlpaSim Evaluation`

## Positioning

Position this as a systems, benchmark, and simulator-adapter paper, not as a new
autonomous driving policy paper. The core claim is that WOD-style trajectory
policies can be adapted into AlpaSim's closed-loop external-driver runtime while
preserving the evidence needed to review the run.

The current artifact is suitable for a workshop, artifact, or reproducibility
track. A stronger full-paper benchmark claim should add multi-scene evaluation,
baselines, failure taxonomy, quantitative runtime metrics, and ablations for
route waypoints, lazy model discovery, idempotent sessions, and launch-state
materialization.

Build locally with:

```bash
make
```
