from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAN_RELATIVE = Path("docs/evidence/benchmark_regeneration_plan_20260706.json")
STATUS_RELATIVE = Path("docs/evidence/benchmark_regeneration_status_20260706.json")
AUDIT_RELATIVE = Path("docs/evidence/benchmark_regeneration_audit_20260706.json")
MANIFEST_RELATIVE = Path("docs/evidence/benchmark_public_evidence_manifest_20260706.json")
PILOT_RELATIVE = Path("docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json")
MISSING_50_RELATIVE = Path("docs/evidence/closed_loop_spotlight_reflex_50scene_batch.json")
MISSING_100_RELATIVE = Path("docs/evidence/closed_loop_spotlight_reflex_100scene_batch.json")


def test_public_evidence_manifest_builder_hashes_tracked_artifacts() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_public_evidence_manifest")

    manifest = module.build_public_evidence_manifest(
        plan_path=ROOT / PLAN_RELATIVE,
        status_path=ROOT / STATUS_RELATIVE,
        audit_path=ROOT / AUDIT_RELATIVE,
        output_path=MANIFEST_RELATIVE,
        repo_root=ROOT,
        created_at="2026-07-06",
    )
    artifacts = {Path(row["path"]): row for row in manifest["artifacts"]}
    pilot = artifacts[PILOT_RELATIVE]

    assert manifest["schema"] == "wod2sim_benchmark_public_evidence_manifest_v1"
    assert manifest["created_at"] == "2026-07-06"
    assert manifest["generator"]["no_download_or_rollout_probes"] is True
    assert manifest["generator"]["excludes_self_hash"] is True
    assert MANIFEST_RELATIVE not in artifacts
    assert pilot["schema"] == "wod2sim_closed_loop_batch_summary_v1"
    assert pilot["claim_scope"] == "claim_valid_10_scene_pilot_summary"
    assert artifacts[STATUS_RELATIVE]["claim_scope"] == "manifest_source_artifact"
    assert pilot["sha256"] == hashlib.sha256((ROOT / PILOT_RELATIVE).read_bytes()).hexdigest()
    assert [row["scene_preset"] for row in manifest["claim_gate"]["scale_claim_gaps"]] == [
        "front_camera_50scene_public2602",
        "front_camera_100scene_public2602",
    ]
    assert manifest["claim_gate"]["scale_claim_gaps"][0]["public_summary_errors"] == [
        "summary_missing"
    ]
    assert manifest["claim_gate"]["scale_claim_gaps"][0]["expected_merge_input_count"] == 5
    assert (
        manifest["claim_gate"]["scale_claim_gaps"][0]["claim_summary_acceptance"]["source_kind"]
        == "merged_batch_summaries"
    )
    assert manifest["claim_gate"]["scale_claim_gaps"][0]["merge_input_progress"] == {
        "claim_valid_count": 0,
        "complete": False,
        "expected_count": 5,
        "invalid_present_count": 0,
        "missing_count": 5,
        "present_count": 0,
    }
    assert {Path(row["path"]) for row in manifest["missing_expected_artifacts"]} == {
        MISSING_50_RELATIVE,
        MISSING_100_RELATIVE,
    }


def test_public_evidence_manifest_main_writes_json_without_runtime_probes() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_public_evidence_manifest")
    with TemporaryDirectory() as tmpdir:
        stdout = Path(tmpdir) / "stdout.json"
        output = Path(tmpdir) / "manifest.json"

        with (
            stdout.open("w", encoding="utf-8") as handle,
            patch.object(
                sys,
                "argv",
                [
                    "wod2sim-benchmark-evidence-manifest",
                    "--repo-root",
                    str(ROOT),
                    "--created-at",
                    "2026-07-06",
                    "--output",
                    str(output),
                    "--json",
                ],
            ),
            patch("sys.stdout", handle),
        ):
            returncode = module.main()

        emitted = json.loads(stdout.read_text(encoding="utf-8"))
        artifact = json.loads(output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert emitted == artifact
    assert artifact["claim_gate"]["valid"] is True
    assert artifact["claim_gate"]["claim_ready"] is False


def test_public_evidence_manifest_recovers_from_stale_manifest_audit_state() -> None:
    module = importlib.import_module("wod2sim.cli.commands.benchmark_public_evidence_manifest")
    audit = json.loads((ROOT / AUDIT_RELATIVE).read_text(encoding="utf-8"))
    audit["valid"] = False
    audit["public_evidence_manifest"]["valid"] = False
    audit["public_evidence_manifest"]["checks"][
        "public_evidence_manifest_hashes_match_tracked_files"
    ] = False

    with TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        evidence = repo_root / "docs" / "evidence"
        evidence.mkdir(parents=True)
        for path in (PLAN_RELATIVE, STATUS_RELATIVE):
            (evidence / path.name).write_text((ROOT / path).read_text(encoding="utf-8"))
        audit_path = evidence / AUDIT_RELATIVE.name
        audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        manifest = module.build_public_evidence_manifest(
            plan_path=PLAN_RELATIVE,
            status_path=STATUS_RELATIVE,
            audit_path=AUDIT_RELATIVE,
            output_path=MANIFEST_RELATIVE,
            repo_root=repo_root,
            created_at="2026-07-06",
        )

    assert manifest["claim_gate"]["valid"] is True
    assert manifest["claim_gate"]["claim_ready"] is False


def test_tracked_public_evidence_manifest_is_public_safe_and_complete() -> None:
    manifest = json.loads((ROOT / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
    rendered = json.dumps(manifest, sort_keys=True)
    artifacts = {Path(row["path"]): row for row in manifest["artifacts"]}

    assert manifest["manifest_artifact"] == MANIFEST_RELATIVE.as_posix()
    assert manifest["source_artifacts"] == {
        "audit": AUDIT_RELATIVE.as_posix(),
        "plan": PLAN_RELATIVE.as_posix(),
        "status": STATUS_RELATIVE.as_posix(),
    }
    assert manifest["artifact_count"] == len(manifest["artifacts"])
    assert "/home/" not in rendered
    assert "REDACTED_SECRET_SENTINEL" not in rendered
    assert MANIFEST_RELATIVE not in artifacts
    assert PILOT_RELATIVE in artifacts
    assert artifacts[PILOT_RELATIVE]["public_safe"] is True
    assert artifacts[PILOT_RELATIVE]["size_bytes"] == (ROOT / PILOT_RELATIVE).stat().st_size
    assert manifest["claim_gate"]["missing_claim_valid_summaries"] == [
        MISSING_50_RELATIVE.as_posix(),
        MISSING_100_RELATIVE.as_posix(),
    ]
    assert len(manifest["claim_gate"]["scale_claim_gaps"]) == 2
    assert manifest["claim_gate"]["scale_claim_gaps"][0]["local_usdz_cache"]["valid"] is False
    assert manifest["claim_gate"]["scale_claim_gaps"][0]["expected_merge_input_count"] == 5
    assert manifest["claim_gate"]["scale_claim_gaps"][1]["expected_merge_input_count"] == 10
    assert (
        manifest["claim_gate"]["scale_claim_gaps"][0]["merge_input_progress"]["present_count"] == 0
    )
    assert (
        manifest["claim_gate"]["scale_claim_gaps"][1]["merge_input_progress"]["missing_count"] == 10
    )
    assert (
        manifest["claim_gate"]["scale_claim_gaps"][0]["source_usdz_cache"]["matching_scene_count"]
        == 0
    )
    assert {Path(row["path"]) for row in manifest["missing_expected_artifacts"]} == {
        MISSING_50_RELATIVE,
        MISSING_100_RELATIVE,
    }
