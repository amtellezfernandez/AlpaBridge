"""Optional BenchStudio integration; importing AlpaBridge never requires BenchStudio."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys

from alpabridge.cli.commands import run_alpasim_scene_batch as batch
from alpabridge.cli.commands.run_alpasim_local_external import MODEL_PRESETS


@dataclass(frozen=True)
class Preparation:
    """Static configuration checks only, not a native simulator qualification."""
    issues: tuple[str, ...]
    native_verified: bool = False

    @property
    def technical_ready(self):
        return not self.issues

    def summary(self):
        return "\n".join(self.issues) if self.issues else (
            "Configuration ready. Native simulator, driver and GPU remain unverified.")


@dataclass(frozen=True)
class BatchResult:
    report: dict

    @property
    def successful(self):
        return (not self.report["failed_runs"]
                and len(self.report["completed_runs"]) == self.report["scene_count"])

    def summary(self):
        return (f"{len(self.report['completed_runs'])}/{self.report['scene_count']} scenes completed; "
                f"{len(self.report['failed_runs'])} failed. Native metrics: {self.report['batch_dir']}")


class AlpaSimPipeline:
    """Use native scene selection, retries and scoring with BenchStudio processes."""

    def __init__(self, *, model, output_dir, alpasim_root, scene_ids=(),
                 scene_preset="fresh_3scene", checkpoint=None, oracle_actor_proxy=None,
                 python=sys.executable, max_retries=1, timeout=900, topology="1gpu"):
        if model not in batch.PUBLIC_RELEASE_MODELS:
            raise ValueError(f"Unsupported AlpaSim model: {model}")
        if scene_preset not in batch.SCENE_PRESETS:
            raise ValueError(f"Unsupported scene preset: {scene_preset}")
        if isinstance(scene_ids, str):
            raise TypeError("scene_ids must be a sequence, not one string")
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
        scenes = batch._selected_scene_ids(self.args)
        if any(not scene or scene in (".", "..") or "/" in scene or "\\" in scene for scene in scenes):
            raise ValueError("scene identifiers cannot contain path separators")

    def check(self):
        """Read configuration and filesystem only; launch no native service."""
        args, issues = self.args, []
        if not args.alpasim_root.is_dir():
            issues.append("AlpaSim checkout directory is missing")
        if shutil.which(args.python) is None:
            issues.append("Selected Python executable is missing")
        if shutil.which("docker") is None:
            issues.append("Docker executable is missing")
        if args.batch_dir.exists():
            issues.append("Output directory already exists; select a fresh batch directory")
        preset = MODEL_PRESETS[args.model]
        for name, required in (("checkpoint", preset.get("checkpoint_required")),
                               ("oracle_actor_proxy", preset.get("requires_oracle_actor_proxy"))):
            path = getattr(args, name)
            if required and path is None:
                issues.append(f"{args.model} requires {name}")
            elif path is not None and not path.is_file():
                issues.append(f"{name} file is missing")
        return Preparation(tuple(issues))

    def run(self):
        report = self.check()
        if not report.technical_ready:
            raise RuntimeError(report.summary())
        # Native driver readiness and artifact audits remain authoritative.
        return BatchResult(batch.execute_batch(self.args))

    __call__ = run


class RecipeFactory:
    def __call__(self, **options):
        return AlpaSimPipeline(**options)

    @staticmethod
    def add_cli_args(parser):
        parser.add_argument("--model", choices=batch.PUBLIC_RELEASE_MODELS, required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--alpasim-root", required=True)
        parser.add_argument("--scene-id", action="append", default=[])
        parser.add_argument("--scene-preset", choices=tuple(batch.SCENE_PRESETS), default="fresh_3scene")
        parser.add_argument("--checkpoint")
        parser.add_argument("--oracle-actor-proxy")
        parser.add_argument("--python", default=sys.executable)
        parser.add_argument("--max-retries", type=int, default=1)
        parser.add_argument("--timeout", type=int, default=900)
        parser.add_argument("--topology", default="1gpu")

    @staticmethod
    def options_from_args(args):
        options = {name: getattr(args, name) for name in (
            "model", "output_dir", "alpasim_root", "scene_preset", "checkpoint",
            "oracle_actor_proxy", "python", "max_retries", "timeout", "topology")}
        return {**options, "scene_ids": args.scene_id}


recipe = RecipeFactory()
