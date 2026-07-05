# Paper

This directory contains the LaTeX source for:

`WOD2Sim: Adapting WOD-Style Driving Policies to Closed-Loop AlpaSim Evaluation`

## Scope

This paper describes WOD2Sim as a systems and evaluation artifact for adapting
WOD-style trajectory policies to AlpaSim's closed-loop external-driver runtime.
It focuses on simulator integration, runtime contract changes, launch
materialization, and auditable evidence artifacts.

The paper does not claim to introduce a new autonomous driving policy or a full
Waymo-to-AlpaSim dataset converter. The current artifact reports integration and
reproducibility evidence, including public setup checks, contract tests, launch
commands, audits, support-bundle hashes, and one recorded AlpaSim closed-loop
run. Larger multi-scene benchmark studies and policy-quality comparisons are
left outside this release.

Build locally with:

```bash
make
```
