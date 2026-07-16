# CLI Reference

Every public entry point installed by the `wod2sim` package. The first four
commands cover the everyday workflow; the rest support batch benchmarking,
evidence packaging, and claim gating.

## Core Workflow

| Command | Purpose |
| --- | --- |
| `wod2sim-doctor` | Validate package install and optional AlpaSim environment. |
| `wod2sim-setup` | Wire WOD2Sim into a local AlpaSim checkout. |
| `wod2sim-ready` | Validate AlpaSim runtime and scene readiness. |
| `wod2sim-reproduce` | Plan or execute the full closed-loop evidence workflow. |

## Run And Launch

| Command | Purpose |
| --- | --- |
| `wod2sim-launch` | Print or launch AlpaSim external-driver runs. |
| `wod2sim-batch` | Run multi-scene closed-loop batches with retries and timeouts. |
| `wod2sim-build-local-cache` | Build a metadata-valid local USDZ cache for larger 26.02 AlpaSim presets. |
| `wod2sim-build-oracle-proxy` | Build the oracle actor proxy required by `direct_actor_planner`. |

## Audit And Evidence

| Command | Purpose |
| --- | --- |
| `wod2sim-audit-run` | Summarize executed run logs and sensor freshness. |
| `wod2sim-audit-signal` | Audit the WOD-signal-to-AlpaSim bridge output. |
| `wod2sim-support-bundle` | Package key run logs, configs, and audit output. |
| `wod2sim-benchmark-summary` | Aggregate evidence directories into one benchmark JSON. |
| `wod2sim-batch-summary` | Summarize `wod2sim-batch` scene runs into public-safe metrics and hashes; merge shard summaries with `--merge-summary`. |
| `wod2sim-evidence` | Render metrics plots from run evidence. |

## Benchmark Regeneration And Claim Gating

These commands maintain the public benchmark evidence chain documented in
[`benchmark_evidence_workflow.md`](benchmark_evidence_workflow.md).

| Command | Purpose |
| --- | --- |
| `wod2sim-benchmark-plan` | Emit the public-safe 10/50/100 benchmark regeneration plan. |
| `wod2sim-benchmark-readiness` | Report host/cache/image readiness without downloads or rollouts. |
| `wod2sim-benchmark-status` | Regenerate public benchmark status from compact evidence artifacts. |
| `wod2sim-benchmark-commands` | Render copyable cache/shard/merge/promotion commands from the plan. |
| `wod2sim-benchmark-operators` | Render the public who-can-review/build/run/promote capability matrix. |
| `wod2sim-benchmark-evidence-manifest` | Hash and classify tracked compact public evidence. |
| `wod2sim-benchmark-cleanup` | Dry-run or remove ignored local benchmark caches and runtime artifacts. |
| `wod2sim-benchmark-audit` | Gate tracked regeneration artifacts against the 10/50/100 claim. |
| `wod2sim-promote-batch-summary` | Promote a generated compact batch summary into public evidence. |

## Public Model Surface

| Model | Use |
| --- | --- |
| `spotlight_reflex` | Checkpoint-free smoke-test adapter. |
| `token_dagger_bc` | Learned policy adapter; requires `--checkpoint /path/to/token_dagger_bc.pt`. |
| `direct_actor_planner` | Planner adapter; requires `--oracle-actor-proxy /path/to/oracle.json`. |

Examples:

```bash
wod2sim-launch --mode print --model spotlight_reflex
wod2sim-launch --mode print --model token_dagger_bc --checkpoint /path/to/token_dagger_bc.pt
wod2sim-build-oracle-proxy --run-dir /path/to/run --output /path/to/oracle.json
wod2sim-launch --mode print --model direct_actor_planner --oracle-actor-proxy /path/to/oracle.json
```

## Environment Variables

Adapter tuning knobs use the `WOD2SIM_` prefix (for example
`WOD2SIM_TOKENBC_SELECTION_MODE`, `WOD2SIM_DIRECT_PLANNER_HORIZON_SECONDS`).
Defaults come from each model's packaged YAML config; environment variables
override per run.

Set `WOD2SIM_ALLOW_UNSUPPORTED_ALPASIM_ARM=1` only when intentionally testing
an unsupported ARM rollout path; the AlpaSim sensorsim image used here is
amd64-only.
