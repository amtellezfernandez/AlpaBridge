"""Optional BenchStudio integration; importing AlpaBridge never requires BenchStudio."""
from __future__ import annotations

import json
import shutil
import sys
from functools import cached_property
from dataclasses import dataclass
from pathlib import Path

from alpabridge.cli.commands import run_alpasim_scene_batch as batch
from alpabridge.cli.commands.run_alpasim_local_external import MODEL_PRESETS


@dataclass(frozen=True)
class BatchResult:
    """Retained native accounting, metrics and audit; no generic success scoring."""
    report: dict
    audit: dict | None = None
    benchmark: dict | None = None

    @property
    def completed(self):
        return (not self.report["failed_runs"]
                and len(self.report["completed_runs"]) == self.report["scene_count"])

    @property
    def successful(self):
        # Completed processes/artifacts alone cannot establish a clean native run.
        return self.completed and self.audit is not None and self.audit["clean_closed_loop_batch"] is True

    @property
    def metrics(self):
        return {} if self.audit is None else self.audit["metrics"]

    def summary(self):
        state = "passed" if self.successful else "not passed"
        lines = [
            f"{len(self.report['completed_runs'])}/{self.report['scene_count']} scenes completed; "
            f"{len(self.report['failed_runs'])} failed; native artifact audit {state}. "
            f"Results: {self.report['batch_dir']}"
        ]
        metrics = "; ".join(
            f"{name}={value['mean']} (n={value['count']})"
            for name, value in self.metrics.items()
        )
        lines.append("Metrics: " + metrics if metrics else "No retained metrics.")
        if self.audit is not None:
            lines.append(self.audit["claim_boundary"])
        return "\n".join(lines)

    @classmethod
    def from_directory(cls, directory):
        """Read native artifacts and compute their existing offline batch summary."""
        from alpabridge.cli.commands.batch_summary import build_summary
        root = Path(directory).resolve()
        report = json.loads((root / "batch-status.json").read_text("utf-8"))
        if not isinstance(report, dict) or report.get("schema") != "alpasim_scene_batch_summary_v1":
            raise ValueError("unsupported AlpaSim batch status")
        runs = report.get("runs")
        count = report.get("scene_count")
        if (not isinstance(runs, list) or type(count) is not int or count < 1
                or len(runs) > count or any(not isinstance(row, dict)
                    or not isinstance(row.get("run_dir"), str) or not row["run_dir"] for row in runs)):
            raise ValueError("malformed AlpaSim batch accounting")
        identities = [row.get("scene_id") for row in runs]
        if any(not isinstance(scene, str) or not scene for scene in identities) or len(set(identities)) != len(identities):
            raise ValueError("missing or duplicate scene identity in batch status")
        # Derive operational counts from retained rows, never trust redundant lists.
        report = {**report, "batch_dir": str(root),
                  "completed_runs": [row["run_dir"] for row in runs if row.get("result") in ("completed", "skipped_completed")],
                  "failed_runs": [row["run_dir"] for row in runs if row.get("result") == "failed"]}
        plan_path = root / "benchmark.json"
        plan = json.loads(plan_path.read_text("utf-8")) if plan_path.exists() else None
        if plan is not None and (not isinstance(plan, dict)
                or plan.get("schema") != "benchstudio.benchmark.v1"
                or plan.get("mode") != "protocol" or plan.get("case_count") != count):
            raise ValueError("native batch does not match its retained benchmark plan")
        return cls(report, build_summary(batch_dir=root), plan)


class AlpaSimPipeline:
    """Use the shared engine with native scene selection and scoring semantics."""

    def __init__(self, *, model, alpasim_root, output_dir=None, config=None, scene_ids=(),
                 scene_preset="fresh_3scene", checkpoint=None, oracle_actor_proxy=None,
                 python=sys.executable, max_retries=None, timeout=None, topology="1gpu",
                 benchmark_revision="alpabridge-scene-protocol-v1",
                 evaluator_revision="alpabridge-native-batch-audit-v1",
                 environment_revision="UNVERIFIED_NATIVE_ENVIRONMENT"):
        run_id = None
        continue_on_error = False
        if config is not None:
            bs = batch._benchstudio()
            if not isinstance(config, bs.EvaluationConfig):
                raise TypeError("config must be bs.EvaluationConfig")
            if output_dir is not None or timeout is not None or max_retries is not None:
                raise ValueError("output_dir, timeout and max_retries belong in config when config is supplied")
            if config.batch_size is not None or config.concurrency != 1:
                raise ValueError("AlpaSim scene batches support sequential execution, not batching/concurrency")
            output_dir, timeout, run_id = config.output_dir, config.timeout, config.run_id
            max_retries, continue_on_error = config.max_retries, config.continue_on_error
        if output_dir is None:
            raise ValueError("provide output_dir or config.output_dir")
        timeout = 900 if timeout is None else timeout
        if type(timeout) is float and timeout.is_integer():
            timeout = int(timeout)
        if model not in batch.PUBLIC_RELEASE_MODELS:
            raise ValueError(f"Unsupported AlpaSim model: {model}")
        if scene_preset not in batch.SCENE_PRESETS:
            raise ValueError(f"Unsupported scene preset: {scene_preset}")
        if isinstance(scene_ids, str):
            raise TypeError("scene_ids must be a sequence, not one string")
        max_retries = 1 if max_retries is None else max_retries
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        if type(timeout) is not int or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        argv = ["--executor", "benchstudio", "--mode", "both", "--model", model,
                "--batch-dir", str(Path(output_dir).resolve()),
                "--alpasim-root", str(Path(alpasim_root).resolve()),
                "--scene-preset", scene_preset, "--python", str(python),
                "--max-retries", str(max_retries), "--timeout", str(timeout),
                "--topology", topology]
        for scene in scene_ids:
            argv.extend(["--scene-id", scene])
        for flag, value in (("--checkpoint", checkpoint),
                            ("--oracle-actor-proxy", oracle_actor_proxy)):
            if value is not None:
                argv.extend([flag, str(Path(value).resolve())])
        self.args = batch._build_parser().parse_args(argv)
        self.args.run_id = run_id or Path(output_dir).name
        self.args.continue_on_error = continue_on_error
        self.args.benchmark_revision = benchmark_revision
        self.args.evaluator_revision = evaluator_revision
        self.args.environment_revision = environment_revision
        scenes = batch._selected_scene_ids(self.args)
        if len(set(scenes)) != len(scenes):
            raise ValueError("scene identifiers must be unique within a batch")
        if any(not scene or scene in (".", "..") or "/" in scene or "\\" in scene for scene in scenes):
            raise ValueError("scene identifiers cannot contain path separators")

    @cached_property
    def benchmark(self):
        return _benchmark(self.args)

    @cached_property
    def engine(self):
        return _make_engine(self.args, self.benchmark)

    def check(self):
        return self.engine.check()

    def run(self):
        return self.engine.run()

    __call__ = run


def _execution_api():
    bs = batch._benchstudio()
    try:
        from benchstudio.backends import CaseResult
    except ImportError as error:
        raise RuntimeError("Upgrade BenchStudio to the reviewed case-execution engine") from error
    return bs, CaseResult


class AlpaSimProtocol:
    """A collection of scenes, not a single model call or success trial."""
    supports_retries = True  # Explicit native infrastructure retry policy.

    def __init__(self, scene_ids):
        try:
            from benchstudio.backends import BenchmarkCase
        except ImportError as error:
            raise RuntimeError("Upgrade BenchStudio to executable benchmark protocols") from error
        self.cases = tuple(BenchmarkCase(scene, {"scene": scene}) for scene in scene_ids)

    def bind(self, system, *, benchmark, config):
        from copy import copy
        # This integration's system is the native launcher configuration selected
        # by AlpaSimPipeline, not a generic scalar inference callback.
        args = copy(system)
        if config.output_dir is None:
            raise ValueError("AlpaSim requires an output directory")
        args.batch_dir = config.output_dir
        return AlpaSimBackend(args)


def _benchmark(args):
    bs, _ = _execution_api()
    return bs.Benchmark(
        "alpasim-scenes", getattr(args, "benchmark_revision", "alpabridge-scene-protocol-v1"),
        evaluator_revision=getattr(args, "evaluator_revision", "alpabridge-native-batch-audit-v1"),
        environment_revision=getattr(args, "environment_revision", "UNVERIFIED_NATIVE_ENVIRONMENT"),
        protocol=AlpaSimProtocol(batch._selected_scene_ids(args)),
    )


def _make_engine(args, benchmark=None):
    bs, _ = _execution_api()
    return bs.EvaluationEngine(system=args, benchmark=benchmark or _benchmark(args),
                               config=_engine_config(args))


def _engine_config(args):
    bs = batch._benchstudio()
    return bs.EvaluationConfig(run_id=args.run_id, output_dir=args.batch_dir,
                              timeout=args.timeout, max_retries=args.max_retries,
                              continue_on_error=args.continue_on_error)


def _static_issues(args):
    issues = []
    if not args.alpasim_root or not args.alpasim_root.is_dir():
        issues.append("AlpaSim checkout directory is missing")
    if shutil.which(args.python) is None:
        issues.append("Selected Python executable is missing")
    if shutil.which("docker") is None:
        issues.append("Docker executable is missing")
    preset = MODEL_PRESETS[args.model]
    for name, required in (("checkpoint", preset.get("checkpoint_required")),
                           ("oracle_actor_proxy", preset.get("requires_oracle_actor_proxy"))):
        path = getattr(args, name)
        if required and path is None:
            issues.append(f"{args.model} requires {name}")
        elif path is not None and not path.is_file():
            issues.append(f"{name} file is missing")
    if args.allow_existing_batch_dir or args.rerun_existing:
        issues.append("the shared engine requires a fresh batch; existing-output recovery is not supported")
    return issues


class AlpaSimBackend:
    """Per-case native execution and reports; scheduling belongs to BenchStudio."""
    supports_timeout = True

    def __init__(self, args):
        self.args = args
        self.cases = tuple(batch._selected_scene_ids(args))
        if (len(set(self.cases)) != len(self.cases) or any(
                not case or case in (".", "..") or "/" in case or "\\" in case for case in self.cases)):
            raise ValueError("scene identities must be unique and cannot contain path separators")
        self.indices = {case: i for i, case in enumerate(self.cases, start=args.scene_offset + 1)}
        self.statuses = {}

    def check(self, config):
        return _static_issues(self.args)

    def start(self, config):
        self.statuses = {}
        batch._write_json(self.args.batch_dir / "batch-manifest.json",
                          batch._batch_manifest(self.args, list(self.cases)))
        self._save()

    def execute_case(self, case, *, attempt, config):
        bs, CaseResult = _execution_api()
        run_dir = self._run_dir(case, attempt)
        run_dir.mkdir(parents=True, exist_ok=False)
        command = batch._scene_command(self.args, scene_id=case, run_dir=run_dir)
        try:
            result = bs.ProcessCommand("scene", tuple(command), batch.RUNNER_CWD,
                                       timeout=config.timeout).execute(run_dir / "process-logs", check=False)
            outcome = CaseResult(result.returncode == 0 and batch._scene_artifacts_complete(command),
                                    {"returncode": result.returncode, "command": command})
        except BaseException as error:
            try:
                batch._cleanup_failed_scene(command, cwd=batch.RUNNER_CWD, strict=True)
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise
        else:
            batch._cleanup_failed_scene(command, cwd=batch.RUNNER_CWD, strict=True)
            return outcome

    def close(self):
        # The native launcher currently owns a complete process per scene. There
        # is no shared server to close here; reusable workers can own one instead.
        pass

    def _run_dir(self, case, attempt):
        return self.args.batch_dir / f"{self.indices[case]:03d}_{case}" / f"attempt-{attempt:04d}"

    def record(self, case, result, *, attempt):
        run_dir = self._run_dir(case, attempt)
        output = result.output or {}
        self.statuses[case] = {
            "index": self.indices[case], "scene_id": case, "run_dir": str(run_dir),
            "command": output.get("command", []), "status": batch._scene_status(run_dir),
            "result": "completed" if result.completed else "failed",
            "returncode": output.get("returncode", 1) if result.completed else (output.get("returncode") or 1),
            "attempts": attempt, "diagnostics": batch._scene_diagnostics(run_dir),
        }
        self._save()

    def _save(self):
        summary = batch._build_batch_summary(batch_dir=self.args.batch_dir,
            mode=self.args.mode, model=self.args.model, scene_count=len(self.cases),
            statuses=list(self.statuses.values()))
        batch._write_json(self.args.batch_dir / "batch-status.json", summary)

    def finish(self):
        return BatchResult.from_directory(self.args.batch_dir)


def run_with_engine(args):
    """Compatibility native CLI route; the batch loop executes only in BenchStudio."""
    from copy import copy
    args = copy(args)
    args.batch_dir = batch._resolve_batch_dir(args)
    args.run_id = getattr(args, "run_id", None) or args.batch_dir.name
    return _make_engine(args).run()


class RecipeFactory:
    def __call__(self, **options):
        return AlpaSimPipeline(**options)

    @staticmethod
    def add_cli_args(parser):
        parser.add_argument("--model", choices=batch.PUBLIC_RELEASE_MODELS, required=True)
        parser.add_argument("--output-dir", "--output", dest="output_dir", required=True)
        parser.add_argument("--alpasim-root", required=True)
        parser.add_argument("--scene-id", action="append", default=[])
        parser.add_argument("--scene-preset", choices=tuple(batch.SCENE_PRESETS), default="fresh_3scene")
        parser.add_argument("--checkpoint")
        parser.add_argument("--oracle-actor-proxy")
        parser.add_argument("--python", default=sys.executable)
        parser.add_argument("--max-retries", type=int, default=1)
        parser.add_argument("--timeout", type=int, default=900)
        parser.add_argument("--topology", default="1gpu")
        parser.add_argument("--run-id", default="evaluation")
        parser.add_argument("--benchmark-revision", default="alpabridge-scene-protocol-v1")
        parser.add_argument("--evaluator-revision", default="alpabridge-native-batch-audit-v1")
        parser.add_argument("--environment-revision", default="UNVERIFIED_NATIVE_ENVIRONMENT")

    @staticmethod
    def options_from_args(args):
        options = {name: getattr(args, name) for name in (
            "model", "output_dir", "alpasim_root", "scene_preset", "checkpoint",
            "oracle_actor_proxy", "python", "max_retries", "timeout", "topology",
            "benchmark_revision", "evaluator_revision", "environment_revision")}
        bs = batch._benchstudio()
        output_dir = options.pop("output_dir")
        timeout = options.pop("timeout")
        max_retries = options.pop("max_retries")
        return {**options, "scene_ids": args.scene_id,
                "config": bs.EvaluationConfig(run_id=args.run_id, output_dir=output_dir, timeout=timeout, max_retries=max_retries)}

    @staticmethod
    def open_run(directory):
        return BatchResult.from_directory(directory)


recipe = RecipeFactory()
