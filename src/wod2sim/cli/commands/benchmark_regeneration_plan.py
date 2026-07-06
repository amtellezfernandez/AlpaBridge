from __future__ import annotations

import argparse
import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.build_alpasim_local_usdz_cache import (
    DEFAULT_HF_REPO,
    DEFAULT_HF_REVISION,
)
from wod2sim.cli.commands.run_alpasim_local_external import (
    PUBLIC_RELEASE_MODELS,
    SCENE_PRESETS,
    _scene_ids,
)

PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
DEFAULT_MODEL = "spotlight_reflex"
DEFAULT_PILOT_PRESET = "front_camera_10scene_smoke"
DEFAULT_SCALE_PRESETS = (
    "front_camera_50scene_public2602",
    "front_camera_100scene_public2602",
)
STATUS_ARTIFACT = "docs/evidence/benchmark_regeneration_status_20260706.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a public-safe, machine-readable plan for regenerating WOD2Sim "
            "closed-loop benchmark artifacts."
        )
    )
    parser.add_argument("--model", choices=PUBLIC_RELEASE_MODELS, default=DEFAULT_MODEL)
    parser.add_argument("--pilot-preset", choices=tuple(SCENE_PRESETS), default=DEFAULT_PILOT_PRESET)
    parser.add_argument(
        "--scale-preset",
        choices=tuple(SCENE_PRESETS),
        action="append",
        default=None,
        help="Scale preset to include. Defaults to the 50/100 public 26.02 presets.",
    )
    parser.add_argument("--alpasim-root", default="/path/to/alpasim")
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--hf-repo", default=DEFAULT_HF_REPO)
    parser.add_argument("--hf-revision", default=DEFAULT_HF_REVISION)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--driver-warmup-seconds", type=float, default=5.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plan = build_plan(
        model=args.model,
        pilot_preset=args.pilot_preset,
        scale_presets=args.scale_preset,
        alpasim_root=args.alpasim_root,
        runs_root=args.runs_root,
        hf_repo=args.hf_repo,
        hf_revision=args.hf_revision,
        timeout=args.timeout,
        driver_warmup_seconds=args.driver_warmup_seconds,
        max_retries=args.max_retries,
        workers=args.workers,
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        _print_human_summary(plan)
    return 0


def build_plan(
    *,
    model: str = DEFAULT_MODEL,
    pilot_preset: str = DEFAULT_PILOT_PRESET,
    scale_presets: list[str] | tuple[str, ...] | None = None,
    alpasim_root: str = "/path/to/alpasim",
    runs_root: str = "runs",
    hf_repo: str = DEFAULT_HF_REPO,
    hf_revision: str = DEFAULT_HF_REVISION,
    timeout: int = 900,
    driver_warmup_seconds: float = 5.0,
    max_retries: int = 1,
    workers: int = 3,
    created_at: str | None = None,
) -> dict[str, Any]:
    if model not in PUBLIC_RELEASE_MODELS:
        raise ValueError(f"unknown public model: {model}")
    selected_scale_presets = tuple(scale_presets or DEFAULT_SCALE_PRESETS)
    _require_preset(pilot_preset)
    for preset in selected_scale_presets:
        _require_preset(preset)

    stages = [
        _stage_plan(
            stage="pilot",
            model=model,
            scene_preset=pilot_preset,
            requires_local_usdz_cache=False,
            alpasim_root=alpasim_root,
            runs_root=runs_root,
            hf_repo=hf_repo,
            hf_revision=hf_revision,
            timeout=timeout,
            driver_warmup_seconds=driver_warmup_seconds,
            max_retries=max_retries,
            workers=workers,
        )
    ]
    stages.extend(
        _stage_plan(
            stage=_scale_stage_name(preset),
            model=model,
            scene_preset=preset,
            requires_local_usdz_cache=True,
            alpasim_root=alpasim_root,
            runs_root=runs_root,
            hf_repo=hf_repo,
            hf_revision=hf_revision,
            timeout=timeout,
            driver_warmup_seconds=driver_warmup_seconds,
            max_retries=max_retries,
            workers=workers,
        )
        for preset in selected_scale_presets
    )

    return {
        "schema": PLAN_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "objective": (
            "Regenerate WOD2Sim closed-loop benchmark artifacts from scratch, validate "
            "the 10-scene pilot, and scale to the 50/100-scene public presets when an "
            "x86_64 AlpaSim runner is available."
        ),
        "status_artifact": STATUS_ARTIFACT,
        "public_artifact_policy": {
            "tracked": "Compact JSON summaries, commands, tests, and public-safe metrics/hashes.",
            "untracked": (
                "Raw AlpaSim media, support bundles, USDZ assets, Hugging Face caches, "
                "Docker layers, and gated scene-derived files."
            ),
        },
        "who_can_do_what": [
            {
                "role": "reviewer",
                "can_do": "Review docs, run package tests, inspect dry plans and compact summaries.",
                "requirements": "Python checkout; no AlpaSim, Docker, GPU, or gated assets required.",
            },
            {
                "role": "cache_builder",
                "can_do": "Build metadata-valid local USDZ directories for 26.02 presets.",
                "requirements": "Hugging Face access, disk capacity, and Python dependencies; GPU optional.",
            },
            {
                "role": "closed_loop_runner",
                "can_do": "Execute live AlpaSim batches and produce claim-valid batch summaries.",
                "requirements": (
                    "x86_64 Linux, Docker, NVIDIA GPU runtime, AlpaSim images, and cached "
                    "scene artifacts."
                ),
            },
            {
                "role": "arm_linux_host",
                "can_do": "Build caches or run diagnostics.",
                "requirements": (
                    "Live sensorsim rollouts are disabled by default because the required "
                    "SensorSim image is amd64-only."
                ),
            },
        ],
        "stages": stages,
    }


def _stage_plan(
    *,
    stage: str,
    model: str,
    scene_preset: str,
    requires_local_usdz_cache: bool,
    alpasim_root: str,
    runs_root: str,
    hf_repo: str,
    hf_revision: str,
    timeout: int,
    driver_warmup_seconds: float,
    max_retries: int,
    workers: int,
) -> dict[str, Any]:
    scene_count = len(_scene_ids_for(scene_preset))
    run_dir = _join(runs_root, f"benchmark_{model}_{scene_count}scene")
    local_usdz_dir = (
        _join(
            alpasim_root,
            "data",
            "nre-artifacts",
            f"local-{_revision_label(hf_revision)}-usdzs-{scene_count}",
        )
        if requires_local_usdz_cache
        else None
    )

    commands: dict[str, Any] = {
        "build_local_cache": None,
        "run_batch": _command(
            _batch_argv(
                model=model,
                scene_preset=scene_preset,
                alpasim_root=alpasim_root,
                run_dir=run_dir,
                timeout=timeout,
                driver_warmup_seconds=driver_warmup_seconds,
                max_retries=max_retries,
                local_usdz_dir=local_usdz_dir,
            )
        ),
        "write_batch_summary": _command(
            [
                "wod2sim-batch-summary",
                "--batch-dir",
                run_dir,
                "--output",
                _join(run_dir, "wod2sim-batch-summary.json"),
                "--strict",
                "--json",
            ]
        ),
    }
    if local_usdz_dir is not None:
        commands["build_local_cache"] = _command(
            [
                "wod2sim-build-local-cache",
                "--scene-preset",
                scene_preset,
                "--alpasim-root",
                alpasim_root,
                "--local-usdz-dir",
                local_usdz_dir,
                "--hf-repo",
                hf_repo,
                "--hf-revision",
                hf_revision,
                "--workers",
                str(max(1, workers)),
            ],
            env={"HF_TOKEN": "required"},
        )

    return {
        "stage": stage,
        "scene_preset": scene_preset,
        "scene_count": scene_count,
        "requires_local_usdz_cache": requires_local_usdz_cache,
        "local_usdz_dir": local_usdz_dir,
        "run_dir": run_dir,
        "public_summary_target": (
            f"docs/evidence/closed_loop_{model}_{scene_count}scene_batch.json"
        ),
        "commands": commands,
    }


def _batch_argv(
    *,
    model: str,
    scene_preset: str,
    alpasim_root: str,
    run_dir: str,
    timeout: int,
    driver_warmup_seconds: float,
    max_retries: int,
    local_usdz_dir: str | None,
) -> list[str]:
    argv = [
        "wod2sim-batch",
        "--mode",
        "both",
        "--model",
        model,
        "--scene-preset",
        scene_preset,
        "--alpasim-root",
        alpasim_root,
        "--batch-dir",
        run_dir,
        "--timeout",
        str(timeout),
        "--driver-warmup-seconds",
        _format_number(driver_warmup_seconds),
        "--max-retries",
        str(max_retries),
        "--continue-on-error",
    ]
    if local_usdz_dir is not None:
        argv.extend(["--wizard-arg", f"scenes.local_usdz_dir={local_usdz_dir}"])
    return argv


def _scene_ids_for(scene_preset: str) -> list[str]:
    return _scene_ids(scene_preset, [])


def _command(argv: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "argv": argv,
        "display": _display_command(argv, env=env),
    }
    if env:
        payload["env"] = dict(env)
    return payload


def _display_command(argv: list[str], *, env: dict[str, str] | None = None) -> str:
    prefix = []
    if env:
        prefix = [f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())]
    return " ".join(prefix + [shlex.join(argv)])


def _scale_stage_name(scene_preset: str) -> str:
    if "50scene" in scene_preset:
        return "workshop_scale"
    if "100scene" in scene_preset:
        return "stronger_benchmark"
    return "scale"


def _revision_label(hf_revision: str) -> str:
    return "".join(character for character in hf_revision if character.isalnum())


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _join(root: str, *parts: str) -> str:
    value = root.rstrip("/")
    for part in parts:
        value = f"{value}/{part.strip('/')}"
    return value


def _require_preset(scene_preset: str) -> None:
    if scene_preset not in SCENE_PRESETS:
        raise ValueError(f"unknown scene preset: {scene_preset}")


def _print_human_summary(plan: dict[str, Any]) -> None:
    print(f"{plan['schema']} for {plan['model']}")
    print(f"status_artifact={plan['status_artifact']}")
    for stage in plan["stages"]:
        print(
            f"- {stage['stage']}: {stage['scene_preset']} "
            f"({stage['scene_count']} scenes) -> {stage['public_summary_target']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
