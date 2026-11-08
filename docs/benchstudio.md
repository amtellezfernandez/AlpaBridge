# Evaluate AlpaSim scenes with BenchStudio

AlpaBridge provides the installed `alpasim` pipeline. It uses BenchStudio's
process ownership, separate stdout/stderr logs and structured execution receipts,
while retaining AlpaBridge's scene selection, per-scene native launcher, Docker
cleanup, artifact audits and batch summaries. The existing BenchStudio engine
owns case ordering, retry scheduling and execution receipts. No extra operator script is needed.

Install AlpaBridge in the operator environment (`python -m pip install -e .`).
Install the reviewed BenchStudio distribution separately: it must provide
`ProcessCommand.execute`, shared `EvaluationCheck.summary` and native result reading. BenchStudio is currently private; this optional
integration does not add an inaccessible dependency to AlpaBridge's public install.
Reviewed core implementation: [BenchStudio #37](https://github.com/amtellezfernandez/BenchStudio/pull/37),
commit `dc89e9f4ee3e45f56d47eaa7ea738ad92e789879`.
It does not change either project's license. The default `alpabridge-batch`
executor remains available without BenchStudio.

```python
import benchstudio as bs

config = bs.EvaluationConfig(run_id="route-following", output_dir="runs/route-following-batch", timeout=900)
evaluation = bs.pipeline(
    "alpasim",
    model="route_following",
    alpasim_root="/opt/alpasim",
    config=config,
    scene_ids=("YOUR_INSTALLED_SCENE_ID",),
)
print(evaluation.check().summary())
# Explicit execution, after provisioning the native stack:
results = evaluation()
print(results.summary())
```

The CLI constructs the same pipeline:

```bash
benchstudio evaluate --recipe alpasim --model route_following \
  --alpasim-root /opt/alpasim --output-dir runs/route-following-batch \
  --scene-id YOUR_INSTALLED_SCENE_ID --check
```

Remove `--check` to execute explicitly. `check()` is read-only: it checks selected
configuration, required checkpoint/proxy files, directories and executable
presence. It never invokes Docker, imports a learned model or starts a simulator.
A successful check does **not** qualify the GPU, assets, driver, checkpoint
semantics or scientific protocol. Native readiness checks still run in the
existing launcher. Use the native setup/readiness tooling to provision that stack.

The five existing batch presets are `constant_velocity`, `route_following`,
`mpc_planner`, `token_dagger_bc` and `direct_actor_planner`. The last two retain
their native checkpoint/oracle-proxy requirements. Configure them with `checkpoint=`
and `oracle_actor_proxy=` (CLI: `--checkpoint`, `--oracle-actor-proxy`).
The integration does not automatically download arbitrary checkpoints.

Each attempt retains `SCENE/attempt-NNNN/process-logs/scene.{stdout.log,stderr.log,receipt.json}`
under its batch directory; output is retained there rather than streamed to the
terminal. Native `batch-manifest.json` and `batch-status.json` remain authoritative
for scene accounting. `results.report` contains that native summary.
`results.completed` means all selected scenes completed the operational artifact
contract. `results.successful` additionally requires the existing native batch
audit to accept completeness, provenance, sensor and route contracts. It is not
a claim of successful driving or scientific qualification.
Exit zero without required artifacts remains a failed attempt. Nonzero exits are
recorded before native retry handling. Interruption terminates the owned process
and invokes native container cleanup without retrying the interruption.

This migration has synthetic process and contract tests only. Native AlpaSim
parity, GPU performance and real policy execution have not been validated by this
change. Driver transport, camera/trajectory semantics and domain scoring stay in
AlpaBridge; they are not reimplemented in BenchStudio.

## Common configuration and results

AlpaSim uses the same `bs.EvaluationConfig` and `bs.EvaluationCheck` as callable
systems. `check().configuration_valid` is static compatibility only;
`native_verified` remains false. `technical_ready` is a compatibility alias.
Specify `output_dir` and `timeout` either in `config` or as direct arguments,
not both. The native timeout is a positive integer number of seconds. Async
concurrency and model batching are explicitly rejected for this sequential native
scene runner. `run_id` is recorded in the batch manifest; it is not a global lock.
The CLI accepts `--run-id` and `--output-dir` (`--output` is a compatibility alias).

After running, metrics and failure details require no separate summary command:

```python
print(results.metrics)  # native per-metric mean, count, min/max and interpretation
print(results.audit["failure_taxonomy"])
print(results.summary())

# Later, in a fresh process with AlpaBridge installed:
results = bs.open_run("runs/route-following-batch", backend="alpasim")
print(results.summary())
```

Reopening reads `batch-status.json` and the existing native batch-summary logic.
It parses retained metrics and computes the native artifact summary without
running models, drivers, Docker or simulators, and without rewriting the evidence.
Keep the native batch at its recorded location; relocation of embedded scene paths
is not implemented. No generic trial records or new task-success labels are
invented. `results.audit` retains native provenance, coverage, failure taxonomy
and the native claim boundary. Missing metric values remain missing; each present
metric reports its actual coverage count. These are local trusted-host artifacts,
not a signed BenchStudio system-run manifest or independent evaluator qualification.
The default `bs.open_run(path)` retains its original digest-verified system format;
select `backend="alpasim"` explicitly to read this native format.

## Shared case-execution engine

The installed pipeline exposes `evaluation.engine`, the existing
`bs.EvaluationEngine`. Its adapter implements `execute_case(...)`; there is no
public session object and no invocation of the old batch/retry loop on this route.
`alpabridge-batch --executor benchstudio --mode both` delegates to the same engine.
The standalone subprocess executor and print-only preview preserve their public
package compatibility path.

The engine owns case dispatch, retry/continuation policy, output reservation,
attempt receipts and worker startup/shutdown. A backend can retain loaded weights,
servers or compiled state across cases while isolating simulator or conversation
state per request. This AlpaSim adapter currently keeps the existing complete native
launcher per scene; warm-model reuse has not been implemented or measured here.

Each attempt gets its own directory. A stale aggregate from an earlier failed
attempt cannot make a later attempt appear complete. Native batch reports reference
the latest attempt; earlier receipts and artifacts remain retained. Request cleanup
runs on success, failure, timeout and interruption. Docker cleanup uses a retained
BenchStudio process with a 30-second command deadline; a nonzero cleanup exit is an
incident that stops execution rather than being silently ignored.

Core `EvaluationConfig.max_retries` defaults to zero and `continue_on_error` to
false. AlpaBridge's compatibility arguments and existing CLI retain their native
retry default of one; set `max_retries=0` or `--max-retries 0` to disable it. When
supplying config, put retry settings there. Only incomplete operational results
are retryable. Model/task failure is not a retry condition. Exceptions, deadline
incidents and interruption stop without retrying.

The adapter enforces `config.timeout` on each scene command. The native wizard
still receives its timeout flag independently; the outer command deadline includes
that command's setup. These changed lifecycle/deadline semantics and per-attempt
directories require native validation before scientific use. Arbitrary filesystem
operations are not bounded by a whole-machine deadline.

`execution.json` and `cases.jsonl` sit alongside native reports. Existing-output
recovery, concurrent backend execution, model batching and GPU allocation are not
implemented on this route. Unsupported options are refused. The scientific
paper/E0 paths, their pinned packages and permissions remain unchanged.
