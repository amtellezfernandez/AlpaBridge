from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from wod2sim.cli.commands.run_alpasim_local_external import (
    DEFAULT_ALPASIM_ROOT,
    DEFAULT_RUNS_ROOT,
    PUBLIC_RELEASE_MODELS,
    SCENE_PRESETS,
    _scene_ids,
)

MANIFEST_SCHEMA = "wod2sim_closed_loop_reproduction_v1"
CLAIM_BOUNDARY = (
    "A valid executed reproduction requires a real AlpaSim checkout, local/gated scene assets, "
    "any model-specific checkpoint or oracle proxy, and a completed wod2sim-launch --mode both run. "
    "Dry runs only produce an auditable command plan."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run or plan the WOD2Sim WOD-style-policy to AlpaSim closed-loop reproduction workflow."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually run setup/readiness/launch/audit/bundle steps. Without this, only write a plan.",
    )
    parser.add_argument(
        "--alpasim-root",
        type=Path,
        default=DEFAULT_ALPASIM_ROOT,
        help="Local AlpaSim checkout containing the required env, scene catalog, and gated assets.",
    )
    parser.add_argument(
        "--model",
        choices=PUBLIC_RELEASE_MODELS,
        default="spotlight_reflex",
        help="Public model preset to reproduce.",
    )
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--oracle-actor-proxy", type=Path, default=None)
    parser.add_argument("--scene-preset", choices=tuple(SCENE_PRESETS), default="fresh_3scene")
    parser.add_argument(
        "--scene-id",
        action="append",
        default=[],
        help="Explicit scene id override. If provided, replaces the preset scene list.",
    )
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--topology", default="1gpu")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--baseport", type=int, default=6000)
    parser.add_argument("--port", type=int, default=6789)
    parser.add_argument("--driver-warmup-seconds", type=float, default=10.0)
    parser.add_argument("--wizard-arg", action="append", default=[])
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip wod2sim-setup when the AlpaSim environment is already wired.",
    )
    parser.add_argument("--json", action="store_true", help="Print the reproduction manifest as JSON.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.run_dir = _resolve_run_dir(args)
    args.evidence_dir = _resolve_evidence_dir(args, run_dir=args.run_dir)
    plan = build_plan(args)
    manifest = _initial_manifest(args, plan)
    evidence_dir = Path(manifest["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence_dir / "closed-loop-reproduction-manifest.json"

    if args.execute:
        _run_plan(plan, manifest, evidence_dir=evidence_dir, manifest_path=manifest_path)
    else:
        manifest["valid_claim_evidence"] = False
        manifest["status"] = "planned"
        manifest["advice"].append("Rerun with --execute on a machine with AlpaSim and gated assets.")
        _write_manifest(manifest_path, manifest)

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        _print_human_manifest(manifest)
    return 0 if manifest["status"] in {"planned", "completed"} else 1


def build_plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    run_dir = _resolve_run_dir(args)
    evidence_dir = _resolve_evidence_dir(args, run_dir=run_dir)
    alpasim_root = args.alpasim_root.resolve()

    steps: list[dict[str, Any]] = []
    if not args.skip_setup:
        steps.append(
            {
                "name": "setup",
                "required_for_claim": True,
                "command": [
                    sys.executable,
                    "-m",
                    "wod2sim.cli.commands.setup_alpasim_local_plugin",
                    "--alpasim-root",
                    str(alpasim_root),
                ],
            }
        )
    steps.append(
        {
            "name": "ready",
            "required_for_claim": True,
            "command": [
                sys.executable,
                "-m",
                "wod2sim.cli.commands.check_alpasim_readiness",
                "--alpasim-root",
                str(alpasim_root),
                "--scene-preset",
                args.scene_preset,
                *[item for scene_id in args.scene_id for item in ("--scene-id", scene_id)],
            ],
        }
    )
    launch_command = [
        sys.executable,
        "-m",
        "wod2sim.cli.commands.run_alpasim_local_external",
        "--mode",
        "both",
        "--model",
        args.model,
        "--scene-preset",
        args.scene_preset,
        "--run-dir",
        str(run_dir),
        "--alpasim-root",
        str(alpasim_root),
        "--topology",
        args.topology,
        "--timeout",
        str(args.timeout),
        "--baseport",
        str(args.baseport),
        "--port",
        str(args.port),
        "--driver-warmup-seconds",
        str(args.driver_warmup_seconds),
        "--allow-existing-run-dir",
    ]
    for scene_id in args.scene_id:
        launch_command.extend(["--scene-id", scene_id])
    for wizard_arg in args.wizard_arg:
        launch_command.extend(["--wizard-arg", wizard_arg])
    if args.checkpoint is not None:
        launch_command.extend(["--checkpoint", str(args.checkpoint.resolve())])
    if args.oracle_actor_proxy is not None:
        launch_command.extend(["--oracle-actor-proxy", str(args.oracle_actor_proxy.resolve())])
    steps.append({"name": "launch_closed_loop", "required_for_claim": True, "command": launch_command})
    steps.append(
        {
            "name": "audit_run",
            "required_for_claim": True,
            "command": [
                sys.executable,
                "-m",
                "wod2sim.cli.commands.audit_run",
                "--run-dir",
                str(run_dir),
                "--audit-dir",
                str(evidence_dir / "audit"),
                "--json",
                "--output",
                str(evidence_dir / "run-audit.json"),
            ],
        }
    )
    steps.append(
        {
            "name": "support_bundle",
            "required_for_claim": True,
            "command": [
                sys.executable,
                "-m",
                "wod2sim.cli.commands.support_bundle",
                "--run-dir",
                str(run_dir),
                "--output",
                str(evidence_dir / "support-bundle.tar.gz"),
                "--json",
                "--output-report",
                str(evidence_dir / "support-bundle-report.json"),
            ],
        }
    )
    for step in steps:
        step["cwd"] = str(Path.cwd())
    return steps


def _initial_manifest(args: argparse.Namespace, plan: list[dict[str, Any]]) -> dict[str, Any]:
    run_dir = _resolve_run_dir(args)
    evidence_dir = _resolve_evidence_dir(args, run_dir=run_dir)
    scene_ids = _scene_ids(args.scene_preset, args.scene_id)
    return {
        "schema": MANIFEST_SCHEMA,
        "status": "running" if args.execute else "planned",
        "valid_claim_evidence": False,
        "claim_boundary": CLAIM_BOUNDARY,
        "mode": "execute" if args.execute else "plan",
        "created_at": _timestamp(),
        "updated_at": _timestamp(),
        "alpasim_root": str(args.alpasim_root.resolve()),
        "model": args.model,
        "scene_preset": args.scene_preset,
        "scene_ids": scene_ids,
        "run_dir": str(run_dir),
        "evidence_dir": str(evidence_dir),
        "requires_gated_or_user_assets": {
            "alpasim_checkout": True,
            "alpasim_scene_assets": True,
            "docker_and_nvidia_runtime": True,
            "checkpoint": args.model == "token_dagger_bc",
            "oracle_actor_proxy": args.model == "direct_actor_planner",
        },
        "user_supplied_artifacts": {
            "checkpoint": None if args.checkpoint is None else str(args.checkpoint.resolve()),
            "oracle_actor_proxy": None
            if args.oracle_actor_proxy is None
            else str(args.oracle_actor_proxy.resolve()),
        },
        "expected_evidence": [
            "launch-metadata.json",
            "run-status.json",
            "driver/*.jsonl",
            "aggregate metrics under aggregate/",
            "run-audit.json",
            "audit/manifest.json",
            "support-bundle.tar.gz",
        ],
        "steps": plan,
        "executed_steps": [],
        "advice": [],
    }


def _run_plan(
    plan: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    evidence_dir: Path,
    manifest_path: Path,
) -> None:
    _write_manifest(manifest_path, manifest)
    for step in plan:
        result = _run_step(step, evidence_dir=evidence_dir)
        manifest["executed_steps"].append(result)
        manifest["updated_at"] = _timestamp()
        _write_manifest(manifest_path, manifest)
        if result["returncode"] != 0:
            manifest["status"] = "failed"
            manifest["valid_claim_evidence"] = False
            manifest["failed_step"] = step["name"]
            manifest["advice"].append(
                f"Step {step['name']} failed. Inspect {result['stdout_log']} and {result['stderr_log']}."
            )
            _write_manifest(manifest_path, manifest)
            return

    run_audit_path = evidence_dir / "run-audit.json"
    support_bundle_path = evidence_dir / "support-bundle.tar.gz"
    run_audit = _load_json(run_audit_path)
    manifest["status"] = "completed"
    manifest["valid_claim_evidence"] = bool(
        run_audit.get("valid") and support_bundle_path.is_file()
    )
    if not manifest["valid_claim_evidence"]:
        manifest["advice"].append(
            "The workflow completed, but the audit did not validate the run as clean closed-loop evidence."
        )
    manifest["updated_at"] = _timestamp()
    _write_manifest(manifest_path, manifest)


def _run_step(step: dict[str, Any], *, evidence_dir: Path) -> dict[str, Any]:
    stdout_log = evidence_dir / f"{step['name']}.stdout.log"
    stderr_log = evidence_dir / f"{step['name']}.stderr.log"
    result = subprocess.run(
        step["command"],
        cwd=step["cwd"],
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_log.write_text(result.stdout, encoding="utf-8")
    stderr_log.write_text(result.stderr, encoding="utf-8")
    return {
        "name": step["name"],
        "returncode": int(result.returncode),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }


def _resolve_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir is not None:
        return args.run_dir.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (args.runs_root.resolve() / f"closed_loop_{args.model}_{args.scene_preset}_{stamp}")


def _resolve_evidence_dir(args: argparse.Namespace, *, run_dir: Path) -> Path:
    if args.evidence_dir is not None:
        return args.evidence_dir.resolve()
    return (run_dir / "closed-loop-evidence").resolve()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _print_human_manifest(manifest: dict[str, Any]) -> None:
    print("WOD2Sim closed-loop reproduction")
    print(f"  status: {manifest['status']}")
    print(f"  valid claim evidence: {manifest['valid_claim_evidence']}")
    print(f"  run dir: {manifest['run_dir']}")
    print(f"  evidence dir: {manifest['evidence_dir']}")
    print(f"  model: {manifest['model']}")
    print(f"  scene count: {len(manifest['scene_ids'])}")
    print("  steps:")
    executed = {step["name"]: step for step in manifest["executed_steps"]}
    for step in manifest["steps"]:
        result = executed.get(step["name"])
        suffix = "planned" if result is None else f"returncode={result['returncode']}"
        print(f"    - {step['name']}: {suffix}")
    if manifest["advice"]:
        print("  advice:")
        for item in manifest["advice"]:
            print(f"    - {item}")


if __name__ == "__main__":
    raise SystemExit(main())
