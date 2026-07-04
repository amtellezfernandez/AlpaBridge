from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shlex
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ALPASIM_ROOT = ROOT / "workspace" / "alpasim"
DEFAULT_RUNS_ROOT = ROOT / "runs"
SCENE_PRESET_ROOT = ROOT / "src" / "minimal_shot_av" / "simulator" / "alpasim_scene_presets"

MODEL_PRESETS = {
    "spotlight_reflex": {
        "config_file": ROOT / "src" / "minimal_shot_av" / "simulator" / "alpasim_configs" / "driver" / "spotlight_reflex.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": None,
        "driver_env": {},
    },
    "direct_actor_planner_oracle": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "direct_actor_planner.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": None,
        "requires_oracle_actor_proxy": True,
        "force_cuda": False,
        "driver_env": {
            "MSA_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            "MSA_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_TOLERANCE_US": "50000",
            "MSA_DIRECT_PLANNER_LOG_PATH": "{run_dir}/driver/direct-planner-log.jsonl",
        },
    },
    "direct_actor_planner_max_clearance_oracle": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "direct_actor_planner.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": None,
        "requires_oracle_actor_proxy": True,
        "force_cuda": False,
        "driver_env": {
            "MSA_DIRECT_PLANNER_SELECTION_OBJECTIVE": "max_clearance",
            "MSA_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            "MSA_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_TOLERANCE_US": "50000",
            "MSA_DIRECT_PLANNER_LOG_PATH": "{run_dir}/driver/direct-planner-log.jsonl",
        },
    },
    "token_dagger_iter2": {
        "config_file": ROOT / "src" / "minimal_shot_av" / "simulator" / "alpasim_configs" / "driver" / "token_dagger_bc.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "driver_env": {},
    },
    "token_dagger_srcdecay": {
        "config_file": ROOT / "src" / "minimal_shot_av" / "simulator" / "alpasim_configs" / "driver" / "token_dagger_srcdecay.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter3_srcdecay" / "token_dagger_bc.pt",
        "driver_env": {},
    },
    "token_dagger_iter2_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_bc_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
        },
    },
    "token_dagger_iter2_hybrid": {
        "config_file": ROOT / "src" / "minimal_shot_av" / "simulator" / "alpasim_configs" / "driver" / "token_dagger_bc.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "hybrid_veto",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_GEOMETRIC_WEIGHT": "0.75",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_HYBRID_VETO_MARGIN": "8.0",
            "MSA_TOKENBC_HYBRID_MAX_GEOMETRIC_RANK": "2",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
        },
    },
    "token_dagger_iter2_hybrid_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_bc_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "hybrid_veto",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_GEOMETRIC_WEIGHT": "0.75",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_HYBRID_VETO_MARGIN": "8.0",
            "MSA_TOKENBC_HYBRID_MAX_GEOMETRIC_RANK": "2",
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
        },
    },
    "token_dagger_iter2_axis_constrained_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_bc_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "axis_constrained",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
        },
    },
    "token_dagger_iter2_axis_constrained_oracle_actor_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_bc_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "requires_oracle_actor_proxy": True,
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "axis_constrained",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
            "MSA_TOKENBC_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            "MSA_TOKENBC_ORACLE_ACTOR_PROXY_TOLERANCE_US": "50000",
        },
    },
    "token_dagger_iter2_axis_lexicographic_oracle_actor_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_bc_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "requires_oracle_actor_proxy": True,
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "axis_lexicographic",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
            "MSA_TOKENBC_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            "MSA_TOKENBC_ORACLE_ACTOR_PROXY_TOLERANCE_US": "50000",
        },
    },
    "token_dagger_iter2_actor_axis_oracle_actor_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_bc_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter2" / "token_dagger_bc.pt",
        "requires_oracle_actor_proxy": True,
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "actor_axis_constrained",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
            "MSA_TOKENBC_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            "MSA_TOKENBC_ORACLE_ACTOR_PROXY_TOLERANCE_US": "50000",
        },
    },
    "token_dagger_srcdecay_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_srcdecay_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter3_srcdecay" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
        },
    },
    "token_dagger_srcdecay_hybrid": {
        "config_file": ROOT / "src" / "minimal_shot_av" / "simulator" / "alpasim_configs" / "driver" / "token_dagger_srcdecay.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter3_srcdecay" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "hybrid_veto",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_GEOMETRIC_WEIGHT": "0.75",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_HYBRID_VETO_MARGIN": "8.0",
            "MSA_TOKENBC_HYBRID_MAX_GEOMETRIC_RANK": "2",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
        },
    },
    "token_dagger_srcdecay_hybrid_clamped": {
        "config_file": ROOT
        / "src"
        / "minimal_shot_av"
        / "simulator"
        / "alpasim_configs"
        / "driver"
        / "token_dagger_srcdecay_clamped.yaml",
        "wizard_driver": "spotlight_reflex",
        "checkpoint": ROOT / "artifacts" / "bc_models_iter3_srcdecay" / "token_dagger_bc.pt",
        "driver_env": {
            "MSA_TOKENBC_SELECTION_MODE": "hybrid_veto",
            "MSA_TOKENBC_HYBRID_TOP_K": "3",
            "MSA_TOKENBC_HYBRID_GEOMETRIC_WEIGHT": "0.75",
            "MSA_TOKENBC_HYBRID_POLICY_TEMPERATURE": "1.0",
            "MSA_TOKENBC_HYBRID_VETO_MARGIN": "8.0",
            "MSA_TOKENBC_HYBRID_MAX_GEOMETRIC_RANK": "2",
            "MSA_TOKENBC_TRAJECTORY_MODE": "clamped_lateral",
            "MSA_TOKENBC_MAX_LATERAL_OFFSET_M": "2.0",
            "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
        },
    },
}

SCENE_PRESETS = {
    "fresh_3scene": SCENE_PRESET_ROOT / "fresh_3scene.yaml",
    "front_camera_10scene_smoke": SCENE_PRESET_ROOT / "front_camera_10scene_smoke.yaml",
    "front_camera_30scene_merged": SCENE_PRESET_ROOT / "front_camera_30scene_merged.yaml",
    "front_camera_collision18": SCENE_PRESET_ROOT / "front_camera_collision18.yaml",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or launch matched AlpaSim local external-driver runs."
    )
    parser.add_argument(
        "--mode",
        choices=("print", "driver", "wizard", "both"),
        default="print",
        help="What to launch. 'print' only writes commands and metadata.",
    )
    parser.add_argument(
        "--model",
        choices=tuple(MODEL_PRESETS),
        default="token_dagger_iter2",
        help="Model/checkpoint preset to evaluate.",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Optional checkpoint override for learned models.",
    )
    parser.add_argument(
        "--oracle-actor-proxy",
        type=Path,
        default=None,
        help="Oracle actor-proxy JSON from scripts/build_alpasim_oracle_actor_proxy.py.",
    )
    parser.add_argument(
        "--scene-preset",
        choices=tuple(SCENE_PRESETS),
        default="fresh_3scene",
        help="Scene list preset extracted from an existing wizard config.",
    )
    parser.add_argument(
        "--scene-id",
        action="append",
        default=[],
        help="Extra scene id override. If provided, replaces the preset scene list.",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Run output directory. Defaults to runs/alpasim_<model>_<preset>_<timestamp>.",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=DEFAULT_RUNS_ROOT,
        help="Parent directory for generated run directories.",
    )
    parser.add_argument(
        "--alpasim-root",
        type=Path,
        default=None,
        help="Path to local AlpaSim checkout with .venv and src/{driver,wizard}. Defaults to $ALPASIM_ROOT or ./workspace/alpasim.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=6789,
        help="External driver port.",
    )
    parser.add_argument(
        "--baseport",
        type=int,
        default=6000,
        help="Wizard baseport override.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Wizard timeout override in seconds.",
    )
    parser.add_argument(
        "--topology",
        default="1gpu",
        help="AlpaSim wizard topology override, e.g. 1gpu or 8gpu_12rollouts.",
    )
    parser.add_argument(
        "--wizard-dry-run",
        action="store_true",
        help="Pass wizard.dry_run=true for config validation without executing rollouts.",
    )
    parser.add_argument(
        "--wizard-arg",
        action="append",
        default=[],
        help="Extra raw Hydra override to append to the AlpaSim wizard command.",
    )
    parser.add_argument(
        "--driver-warmup-seconds",
        type=float,
        default=10.0,
        help="Delay between starting the external driver and launching wizard in mode=both.",
    )
    parser.add_argument(
        "--allow-existing-run-dir",
        action="store_true",
        help="Reuse an existing run dir instead of failing.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    alpasim_root = _resolve_alpasim_root(args.alpasim_root)
    _validate_alpasim_checkout(alpasim_root)
    driver_project = alpasim_root / "src" / "driver"
    wizard_project = alpasim_root / "src" / "wizard"
    alpasim_python = alpasim_root / ".venv" / "bin" / "python"
    alpasim_wizard = alpasim_root / ".venv" / "bin" / "alpasim_wizard"

    if not driver_project.is_dir():
        raise SystemExit(f"AlpaSim driver project not found: {driver_project}")
    if not wizard_project.is_dir():
        raise SystemExit(f"AlpaSim wizard project not found: {wizard_project}")
    if not alpasim_python.is_file():
        raise SystemExit(f"AlpaSim virtualenv python not found: {alpasim_python}")
    if not alpasim_wizard.is_file():
        raise SystemExit(f"AlpaSim wizard binary not found: {alpasim_wizard}")

    scene_ids = _scene_ids(args.scene_preset, args.scene_id)
    _preflight_docker_access()
    _preflight_alpasim_base_image()
    _preflight_platform_compatibility()
    _preflight_nvidia_container_runtime()
    _preflight_scene_artifacts(alpasim_root=alpasim_root, scene_ids=scene_ids)
    run_dir = _resolve_run_dir(args)
    _prepare_run_dir(run_dir, allow_existing=args.allow_existing_run_dir)

    model_preset = MODEL_PRESETS[args.model]
    if model_preset.get("requires_oracle_actor_proxy") and args.oracle_actor_proxy is None:
        raise SystemExit(f"Model preset {args.model!r} requires --oracle-actor-proxy")
    oracle_actor_proxy = args.oracle_actor_proxy.resolve() if args.oracle_actor_proxy else None
    if oracle_actor_proxy is not None and not oracle_actor_proxy.is_file():
        raise SystemExit(f"Oracle actor proxy not found: {oracle_actor_proxy}")
    checkpoint = args.checkpoint.resolve() if args.checkpoint else model_preset["checkpoint"]
    if checkpoint is not None:
        checkpoint = Path(checkpoint).resolve()
        if not checkpoint.is_file():
            raise SystemExit(f"Checkpoint not found: {checkpoint}")

    # Keep the external-driver config separate from wizard-generated files.
    # The wizard writes its own driver-config.yaml into the run directory, which
    # can otherwise overwrite the learned-model config after launch.
    driver_config_path = run_dir / "external-driver-config.yaml"
    _write_driver_config(
        template_path=Path(model_preset["config_file"]),
        output_path=driver_config_path,
        checkpoint=checkpoint,
        port=args.port,
        output_dir=run_dir / "driver",
        force_cuda=bool(model_preset.get("force_cuda", args.model != "spotlight_reflex")),
    )

    driver_cmd = _driver_command(
        alpasim_python=alpasim_python,
        driver_config_path=driver_config_path,
    )
    driver_env = _driver_env(model_preset.get("driver_env", {}), run_dir=run_dir, oracle_actor_proxy=oracle_actor_proxy)
    wizard_cmd = _wizard_command(
        alpasim_wizard=alpasim_wizard,
        wizard_driver=model_preset["wizard_driver"],
        deploy_target=_wizard_deploy_target(),
        run_dir=run_dir,
        scene_ids=scene_ids,
        baseport=args.baseport,
        port=args.port,
        timeout=args.timeout,
        topology=args.topology,
        dry_run=args.wizard_dry_run,
        extra_args=args.wizard_arg,
    )

    metadata = {
        "model": args.model,
        "scene_preset": args.scene_preset,
        "scene_ids": scene_ids,
        "port": args.port,
        "baseport": args.baseport,
        "timeout": args.timeout,
        "topology": args.topology,
        "wizard_dry_run": args.wizard_dry_run,
        "wizard_args": args.wizard_arg,
        "driver_config_template": str(model_preset["config_file"]),
        "driver_config_path": str(driver_config_path),
        "wizard_driver": model_preset["wizard_driver"],
        "wizard_deploy_target": _wizard_deploy_target(),
        "checkpoint": str(checkpoint) if checkpoint else None,
        "oracle_actor_proxy": str(oracle_actor_proxy) if oracle_actor_proxy else None,
        "driver_env": driver_env,
        "driver_command": driver_cmd,
        "wizard_command": wizard_cmd,
    }
    (run_dir / "launch-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "driver-command.sh").write_text(_shell_script(driver_cmd, env=driver_env))
    (run_dir / "wizard-command.sh").write_text(_shell_script(wizard_cmd))

    print(f"Run dir: {run_dir}")
    print(f"Scenes ({len(scene_ids)}): {', '.join(scene_ids)}")
    print()
    print("Driver:")
    print("  " + _format_cmd(driver_cmd, env=driver_env))
    print()
    print("Wizard:")
    print("  " + _format_cmd(wizard_cmd))

    if args.mode == "print":
        return

    if args.mode == "driver":
        raise SystemExit(_run(driver_cmd, cwd=alpasim_root, env=driver_env))
    if args.mode == "wizard":
        raise SystemExit(_run(wizard_cmd, cwd=alpasim_root))

    driver_stdout = (run_dir / "driver.stdout.log").open("w")
    driver_stderr = (run_dir / "driver.stderr.log").open("w")
    process = subprocess.Popen(
        driver_cmd,
        cwd=alpasim_root,
        env=_merged_env(driver_env),
        stdout=driver_stdout,
        stderr=driver_stderr,
        text=True,
        start_new_session=True,
    )
    try:
        time.sleep(args.driver_warmup_seconds)
        wizard_code = _run(wizard_cmd, cwd=alpasim_root)
    finally:
        _terminate_process_group(process)
        driver_stdout.close()
        driver_stderr.close()
    raise SystemExit(wizard_code)


def _scene_ids(scene_preset: str, explicit_scene_ids: list[str]) -> list[str]:
    if explicit_scene_ids:
        return explicit_scene_ids
    preset_path = SCENE_PRESETS[scene_preset]
    if not preset_path.is_file():
        raise SystemExit(f"Scene preset file not found: {preset_path}")
    payload = yaml.safe_load(preset_path.read_text())
    scene_ids = payload.get("scenes", {}).get("scene_ids", [])
    if not scene_ids:
        raise SystemExit(f"No scene_ids found in {preset_path}")
    return [str(scene_id) for scene_id in scene_ids]


def _resolve_alpasim_root(cli_value: Path | None) -> Path:
    if cli_value is not None:
        return cli_value.resolve()
    env_value = os.getenv("ALPASIM_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_ALPASIM_ROOT.resolve()


def _validate_alpasim_checkout(alpasim_root: Path) -> None:
    required_dirs = (
        alpasim_root / "src" / "driver",
        alpasim_root / "src" / "wizard",
    )
    for required_dir in required_dirs:
        if not required_dir.is_dir():
            raise SystemExit(f"AlpaSim checkout missing required path: {required_dir}")

    pyproject_file = alpasim_root / "pyproject.toml"
    if not pyproject_file.is_file():
        raise SystemExit(
            "AlpaSim checkout is missing pyproject.toml at "
            f"{pyproject_file}. Recreate it with ./scripts/bootstrap_alpasim_checkout.sh."
        )

    git_marker = alpasim_root / ".git"
    if not git_marker.exists():
        raise SystemExit(
            "ALPASIM_ROOT points at a copied directory, not a real AlpaSim checkout: "
            f"{alpasim_root}. The wizard resolves configs from the nearest git root and "
            "will fail in this layout. Recreate the nested checkout with "
            "./scripts/bootstrap_alpasim_checkout.sh."
        )


def _resolve_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir is not None:
        return args.run_dir.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (args.runs_root.resolve() / f"alpasim_{args.model}_{args.scene_preset}_{stamp}")


def _preflight_scene_artifacts(*, alpasim_root: Path, scene_ids: list[str]) -> None:
    scene_catalog = alpasim_root / "data" / "scenes" / "sim_scenes.csv"
    if not scene_catalog.is_file():
        return

    scene_rows: dict[str, dict[str, str]] = {}
    with scene_catalog.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            scene_id = str(row.get("scene_id", "")).strip()
            if scene_id:
                scene_rows[scene_id] = row

    missing_catalog = [scene_id for scene_id in scene_ids if scene_id not in scene_rows]
    if missing_catalog:
        raise SystemExit(
            "Scene IDs not found in AlpaSim scene catalog "
            f"{scene_catalog}: {', '.join(missing_catalog)}"
        )

    if os.getenv("HF_TOKEN", "").strip():
        return

    all_usdzs_dir = alpasim_root / "data" / "nre-artifacts" / "all-usdzs"
    missing_artifacts: list[str] = []
    for scene_id in scene_ids:
        row = scene_rows[scene_id]
        repository = str(row.get("artifact_repository", "")).strip().lower()
        artifact_uuid = str(row.get("uuid", "")).strip()
        if repository != "huggingface" or not artifact_uuid:
            continue
        artifact_path = all_usdzs_dir / f"{artifact_uuid}.usdz"
        if not artifact_path.is_file():
            missing_artifacts.append(f"{scene_id}:{artifact_uuid}")

    if missing_artifacts:
        preview = ", ".join(missing_artifacts[:5])
        remainder = len(missing_artifacts) - min(len(missing_artifacts), 5)
        suffix = "" if remainder <= 0 else f", ... (+{remainder} more)"
        raise SystemExit(
            "Missing required local AlpaSim USDZ artifacts under "
            f"{all_usdzs_dir} and HF_TOKEN is not set. "
            f"First missing scene/artifact pairs: {preview}{suffix}. "
            "Populate the local AlpaSim data cache or authenticate to the gated "
            "Hugging Face dataset before launching external-driver runs."
        )


def _preflight_docker_access() -> None:
    result = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").strip()
    if "permission denied" in stderr.lower() and "docker.sock" in stderr.lower():
        raise SystemExit(
            "Docker daemon is not accessible for the current user. "
            "Grant this user access to /var/run/docker.sock (for example via the "
            "docker group) or run on a machine with working docker permissions "
            "before launching AlpaSim external-driver runs."
        )
    raise SystemExit(
        "Docker preflight failed before AlpaSim launch. "
        f"`docker info` exited with code {result.returncode}. "
        f"stderr: {stderr}"
    )


def _preflight_alpasim_base_image() -> None:
    image_tag = os.getenv("ALPASIM_BASE_IMAGE_TAG", "alpasim-base:0.66.0")
    result = subprocess.run(
        ["docker", "image", "inspect", image_tag],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    raise SystemExit(
        f"Required local AlpaSim image is missing: {image_tag}. "
        "Build it first with ./scripts/build_alpasim_base_image.sh."
    )


def _preflight_nvidia_container_runtime() -> None:
    if os.getenv("MSA_SKIP_ALPASIM_GPU_RUNTIME_CHECK", "").strip() == "1":
        return

    image_tag = os.getenv("ALPASIM_BASE_IMAGE_TAG", "alpasim-base:0.66.0")
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--gpus",
            "all",
            image_tag,
            "nvidia-smi",
            "-L",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return

    stderr = (result.stderr or "").strip()
    raise SystemExit(
        "AlpaSim sensorsim requires a working NVIDIA container runtime and a visible CUDA GPU. "
        f"Probe command `docker run --rm --gpus all {image_tag} nvidia-smi -L` failed with code "
        f"{result.returncode}. stderr: {stderr}"
    )


def _preflight_platform_compatibility() -> None:
    machine = platform.machine().lower()
    if machine not in {"aarch64", "arm64"}:
        return
    if os.getenv("MSA_ALLOW_UNSUPPORTED_ALPASIM_ARM", "").strip() == "1":
        return
    raise SystemExit(
        "AlpaSim local external-driver rollouts are not currently supported on ARM hosts in this "
        "repo because the required NRE sensorsim image is amd64-only. On DGX Spark / arm64 we "
        "observed sensorsim either fail under emulation or stall before opening its gRPC port. "
        "Run the AlpaSim matrix on an x86_64 host, or set MSA_ALLOW_UNSUPPORTED_ALPASIM_ARM=1 "
        "to force the launch anyway."
    )


def _prepare_run_dir(run_dir: Path, *, allow_existing: bool) -> None:
    if run_dir.exists():
        if not allow_existing:
            raise SystemExit(f"Run dir already exists: {run_dir}")
    else:
        run_dir.mkdir(parents=True)


def _driver_command(
    *,
    alpasim_python: Path,
    driver_config_path: Path,
) -> list[str]:
    return [
        str(alpasim_python),
        "-m",
        "alpasim_driver.main",
        f"--config-path={driver_config_path.parent}",
        f"--config-name={driver_config_path.name}",
    ]


def _write_driver_config(
    *,
    template_path: Path,
    output_path: Path,
    checkpoint: Path | None,
    port: int,
    output_dir: Path,
    force_cuda: bool,
) -> None:
    if not template_path.is_file():
        raise SystemExit(f"Driver config template not found: {template_path}")
    payload = yaml.safe_load(template_path.read_text())
    if isinstance(payload.get("log_level"), str) and "${wizard." in payload["log_level"]:
        payload["log_level"] = "INFO"
    payload["port"] = int(port)
    payload["output_dir"] = str(output_dir)
    model_cfg = payload.setdefault("model", {})
    if checkpoint is not None:
        model_cfg["checkpoint_path"] = str(checkpoint)
    if force_cuda:
        model_cfg["device"] = "cuda"
    output_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _wizard_command(
    *,
    alpasim_wizard: Path,
    wizard_driver: str,
    deploy_target: str,
    run_dir: Path,
    scene_ids: list[str],
    baseport: int,
    port: int,
    timeout: int,
    topology: str,
    dry_run: bool,
    extra_args: list[str] | None = None,
) -> list[str]:
    cmd = [
        str(alpasim_wizard),
        f"deploy={deploy_target}",
        f"topology={topology}",
        f"driver={wizard_driver}",
        f"wizard.log_dir={run_dir}",
        f"wizard.baseport={baseport}",
        f"wizard.timeout={timeout}",
        f"wizard.external_services.driver=[localhost:{port}]",
        f"wizard.dry_run={'true' if dry_run else 'false'}",
        f"scenes.scene_ids={json.dumps(scene_ids)}",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def _wizard_deploy_target() -> str:
    override = os.getenv("MSA_ALPASIM_DEPLOY_TARGET", "").strip()
    if override:
        return override
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "local_arm_external_driver"
    return "local_external_driver"


def _shell_script(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n" + _format_cmd(cmd, env=env) + "\n"


def _format_cmd(cmd: list[str], *, env: dict[str, str] | None = None) -> str:
    prefix = ""
    if env:
        prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items()) + " "
    return prefix + " ".join(shlex.quote(part) for part in cmd)


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    result = subprocess.run(cmd, cwd=cwd, env=_merged_env(env), check=False)
    return int(result.returncode)


def _driver_env(values: dict[str, str], *, run_dir: Path, oracle_actor_proxy: Path | None = None) -> dict[str, str]:
    format_values = {
        "run_dir": run_dir,
        "oracle_actor_proxy_path": "" if oracle_actor_proxy is None else str(oracle_actor_proxy),
    }
    return {str(key): str(value).format(**format_values) for key, value in values.items()}


def _merged_env(extra: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    return env


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
