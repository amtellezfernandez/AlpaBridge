from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "wod2sim_benchmark_public_evidence_manifest_v1"
PLAN_SCHEMA = "wod2sim_benchmark_regeneration_plan_v1"
STATUS_SCHEMA = "wod2sim_benchmark_regeneration_status_v1"
AUDIT_SCHEMA = "wod2sim_benchmark_regeneration_audit_v1"
DEFAULT_MANIFEST = Path("docs/evidence/benchmark_public_evidence_manifest_20260706.json")
DEFAULT_EVIDENCE_DIR = Path("docs/evidence")
DEFAULT_PLAN = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
DEFAULT_STATUS = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
DEFAULT_AUDIT = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a public-safe manifest of tracked compact benchmark evidence. "
            "This command only reads JSON evidence files and computes local hashes; "
            "it never probes Docker, GPUs, scene caches, or gated assets."
        )
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    manifest = build_public_evidence_manifest(
        evidence_dir=args.evidence_dir,
        plan_path=args.plan,
        status_path=args.status,
        audit_path=args.audit,
        output_path=args.output or DEFAULT_MANIFEST,
        repo_root=args.repo_root,
        created_at=args.created_at,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        _print_human_summary(manifest)
    return 0


def build_public_evidence_manifest(
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    plan_path: Path = DEFAULT_PLAN,
    status_path: Path = DEFAULT_STATUS,
    audit_path: Path = DEFAULT_AUDIT,
    output_path: Path = DEFAULT_MANIFEST,
    repo_root: Path = Path.cwd(),
    created_at: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    resolved_evidence_dir = _resolve_path(repo_root, evidence_dir)
    plan = _read_json(_resolve_path(repo_root, plan_path))
    status = _read_json(_resolve_path(repo_root, status_path))
    audit = _read_json(_resolve_path(repo_root, audit_path))

    _require_schema(plan, PLAN_SCHEMA, "plan")
    _require_schema(status, STATUS_SCHEMA, "status")
    _require_schema(audit, AUDIT_SCHEMA, "audit")

    output_display = _display_path(output_path)
    source_paths = {
        _display_path(_relative_to_repo(_resolve_path(repo_root, path), repo_root))
        for path in (plan_path, status_path, audit_path)
    }
    artifacts = [
        _artifact_entry(
            path,
            repo_root=repo_root,
            audit=audit,
            status=status,
            source_paths=source_paths,
        )
        for path in sorted(resolved_evidence_dir.glob("*.json"))
        if _display_path(_relative_to_repo(path, repo_root)) != output_display
    ]
    missing_claim_summaries = [
        {
            "path": path,
            "present": False,
            "required_for_full_claim": True,
            "claim_scope": "missing_claim_valid_scale_summary",
        }
        for path in audit.get("missing_claim_valid_summaries", [])
    ]

    return {
        "schema": MANIFEST_SCHEMA,
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "manifest_artifact": output_display,
        "source_artifacts": {
            "plan": _display_path(plan_path),
            "status": _display_path(status_path),
            "audit": _display_path(audit_path),
        },
        "generator": {
            "command": "wod2sim-benchmark-evidence-manifest",
            "no_download_or_rollout_probes": True,
            "excludes_self_hash": True,
        },
        "claim_gate": {
            "valid": _audit_valid_without_public_evidence_manifest(audit),
            "claim_ready": bool(audit.get("claim_ready")),
            "missing_claim_valid_summaries": list(audit.get("missing_claim_valid_summaries", [])),
            "strict_command": "wod2sim-benchmark-audit --strict --json",
        },
        "public_artifact_policy": _dict_or_empty(status.get("public_artifact_policy")),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "missing_expected_artifacts": missing_claim_summaries,
    }


def _audit_valid_without_public_evidence_manifest(audit: dict[str, Any]) -> bool:
    required_sections = (
        "status_consistency",
        "readiness_consistency",
        "diagnostic_evidence",
        "regeneration_commands",
        "operator_matrix",
    )
    return not audit.get("errors") and all(
        _dict_or_empty(audit.get(section)).get("valid") is True
        for section in required_sections
    )


def _artifact_entry(
    path: Path,
    *,
    repo_root: Path,
    audit: dict[str, Any],
    status: dict[str, Any],
    source_paths: set[str],
) -> dict[str, Any]:
    relative = _relative_to_repo(path, repo_root)
    raw = path.read_bytes()
    payload = _try_read_json(raw)
    return {
        "path": _display_path(relative),
        "present": True,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema") if isinstance(payload, dict) else None,
        "artifact_type": _artifact_type(relative),
        "claim_scope": _claim_scope(
            relative,
            payload=payload,
            audit=audit,
            status=status,
            source_paths=source_paths,
        ),
        "public_safe": True,
    }


def _artifact_type(path: Path) -> str:
    name = path.name
    if name.startswith("closed_loop_"):
        return "closed_loop_summary"
    if name.startswith("benchmark_regeneration_"):
        return "benchmark_regeneration_control"
    if name.startswith("benchmark_operator_matrix"):
        return "operator_capability_matrix"
    return "public_evidence"


def _claim_scope(
    path: Path,
    *,
    payload: object,
    audit: dict[str, Any],
    status: dict[str, Any],
    source_paths: set[str],
) -> str:
    display = _display_path(path)
    if display in source_paths:
        return "manifest_source_artifact"
    if display in audit.get("missing_claim_valid_summaries", []):
        return "missing_claim_valid_scale_summary"
    if not isinstance(payload, dict):
        return "public_evidence_metadata"
    if payload.get("schema") == "wod2sim_closed_loop_batch_summary_v1":
        aggregate = _dict_or_empty(payload.get("aggregate"))
        scene_count = aggregate.get("planned_scene_count")
        if payload.get("clean_closed_loop_batch") is True and scene_count == 10:
            return "claim_valid_10_scene_pilot_summary"
        return "diagnostic_summary_not_full_stage_claim"
    evidence_artifacts = _dict_or_empty(status.get("evidence_artifacts"))
    if display in set(str(value) for value in evidence_artifacts.values()):
        return "tracked_evidence_chain_artifact"
    return "supporting_public_evidence"


def _try_read_json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON at {path}")
    return payload


def _require_schema(payload: dict[str, Any], schema: str, label: str) -> None:
    actual = payload.get("schema")
    if actual != schema:
        raise ValueError(f"{label} schema must be {schema}, got {actual!r}")


def _resolve_path(repo_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def _relative_to_repo(path: Path, repo_root: Path) -> Path:
    try:
        return path.resolve().relative_to(repo_root)
    except ValueError:
        return path


def _display_path(path: Path) -> str:
    return str(path) if path.is_absolute() else path.as_posix()


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _print_human_summary(manifest: dict[str, Any]) -> None:
    print(manifest["schema"])
    print(f"- artifact_count: {manifest['artifact_count']}")
    print(f"- claim_ready: {manifest['claim_gate']['claim_ready']}")
    for missing in manifest["missing_expected_artifacts"]:
        print(f"- missing: {missing['path']}")


if __name__ == "__main__":
    raise SystemExit(main())
