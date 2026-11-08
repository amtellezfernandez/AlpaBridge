# Evaluate AlpaSim scenes with BenchStudio

AlpaBridge provides the installed `alpasim` pipeline. It uses BenchStudio's
process ownership, separate stdout/stderr logs and structured execution receipts,
while retaining AlpaBridge's scene selection, native launcher, retries, Docker
cleanup, artifact audits and batch summaries. No extra operator script is needed.

Install AlpaBridge in the operator environment (`python -m pip install -e .`).
Install the reviewed BenchStudio distribution separately: it must provide
`ProcessCommand.execute`. BenchStudio is currently private; this optional
integration does not add an inaccessible dependency to AlpaBridge's public install.
Reviewed core implementation: [BenchStudio #35](https://github.com/amtellezfernandez/BenchStudio/pull/35),
commit `bb7d787cf7bd070964afe67e72d7fdb3cb7abca2`.
It does not change either project's license. The default `alpabridge-batch`
executor remains available without BenchStudio.

```python
import benchstudio as bs

evaluation = bs.pipeline(
    "alpasim",
    model="route_following",
    alpasim_root="/opt/alpasim",
    output_dir="runs/route-following-batch",
    scene_ids=("YOUR_INSTALLED_SCENE_ID",),
)
print(evaluation.check().summary())
# Explicit execution, after provisioning the native stack:
results = evaluation.run()
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

Each attempt retains `process-logs/attempt-*/scene.{stdout.log,stderr.log,receipt.json}`
under its scene directory; output is retained there rather than streamed to the
terminal. Native `batch-manifest.json` and `batch-status.json` remain authoritative
for scene accounting. `results.report` contains that native summary.
`results.successful` means all selected scenes completed the existing native
artifact contract; it is not a driving-performance or scientific-validity claim.
Exit zero without required artifacts remains a failed attempt. Nonzero exits are
recorded before native retry handling. Interruption terminates the owned process
and invokes native container cleanup without retrying the interruption.

This migration has synthetic process and contract tests only. Native AlpaSim
parity, GPU performance and real policy execution have not been validated by this
change. Driver transport, camera/trajectory semantics and domain scoring stay in
AlpaBridge; they are not reimplemented in BenchStudio.
