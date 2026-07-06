from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
READINESS_RELATIVE = Path("docs/evidence/benchmark_regeneration_readiness_20260706.json")


class BenchmarkRegenerationReadinessTests(unittest.TestCase):
    def test_build_report_uses_non_destructive_probes_and_validates_scale_cache(self) -> None:
        from wod2sim.cli.commands import benchmark_regeneration_readiness as module
        from wod2sim.cli.commands.run_alpasim_local_external import _scene_ids

        seen_commands: list[list[str]] = []

        def fake_runner(argv: list[str]) -> dict[str, object]:
            seen_commands.append(argv)
            stdout = ""
            if argv[:2] == ["docker", "info"] and "Runtimes" in argv[-1]:
                stdout = "runc\nnvidia"
            elif argv[:2] == ["docker", "info"]:
                stdout = "26.0.0"
            elif argv[:3] == ["docker", "image", "inspect"]:
                stdout = "sha256:alpasim-base"
            elif argv[0] == "nvidia-smi":
                stdout = "GPU 0: test"
            return {
                "ok": True,
                "status": "ok",
                "argv": argv,
                "returncode": 0,
                "stdout": stdout,
                "stderr": "",
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alpasim_root = root / "alpasim"
            cache_dir = alpasim_root / "data" / "nre-artifacts" / "local-2602-usdzs-3"
            cache_dir.mkdir(parents=True)
            for index, scene_id in enumerate(_scene_ids("fresh_3scene", []), start=1):
                _write_usdz(cache_dir / f"uuid-{index}.usdz", scene_id=scene_id, uuid=f"uuid-{index}")

            report = module.build_readiness_report(
                pilot_preset="fresh_3scene",
                scale_presets=["fresh_3scene"],
                alpasim_root=alpasim_root,
                repo_root=root,
                created_at="2026-07-06",
                env={"HF_TOKEN": "token"},
                command_runner=fake_runner,
                disk_usage=lambda _path: _DiskUsage(),
            )

        scale_stage = report["stages"][1]
        self.assertEqual("wod2sim_benchmark_regeneration_readiness_v1", report["schema"])
        self.assertTrue(report["no_download_or_rollout_probes"])
        self.assertTrue(report["readiness"]["all_scale_caches_valid"])
        self.assertTrue(report["readiness"]["closed_loop_runner_ready"])
        self.assertFalse(report["readiness"]["claim_valid_scale_summaries_present"])
        self.assertTrue(scale_stage["local_usdz_cache"]["validation"]["valid"])
        self.assertFalse(scale_stage["public_summary"]["present"])
        self.assertIn(
            "fresh_3scene_claim_summary_missing",
            {requirement["id"] for requirement in report["blocking_requirements"]},
        )
        self.assertEqual("refresh_readiness", report["next_command_groups"][0]["name"])
        self.assertEqual("verify_claim_gate", report["next_command_groups"][-1]["name"])
        self.assertFalse(any(command[:2] == ["docker", "run"] for command in seen_commands))

    def test_build_report_marks_arm_host_and_missing_cache_not_ready(self) -> None:
        from wod2sim.cli.commands import benchmark_regeneration_readiness as module

        def failing_runner(argv: list[str]) -> dict[str, object]:
            return {
                "ok": False,
                "status": "failed",
                "argv": argv,
                "returncode": 1,
                "stdout": "",
                "stderr": "missing",
            }

        with tempfile.TemporaryDirectory() as tmp, patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="aarch64"
        ):
            report = module.build_readiness_report(
                pilot_preset="fresh_3scene",
                scale_presets=["fresh_3scene"],
                alpasim_root=Path(tmp) / "alpasim",
                repo_root=Path(tmp),
                created_at="2026-07-06",
                env={},
                command_runner=failing_runner,
                disk_usage=lambda _path: _DiskUsage(),
            )

        scale_stage = report["stages"][1]
        self.assertFalse(report["host"]["closed_loop_runner_supported"])
        self.assertTrue(report["host"]["arm_host"])
        self.assertFalse(report["readiness"]["cache_build_ready"])
        self.assertFalse(report["readiness"]["closed_loop_runner_ready"])
        self.assertFalse(scale_stage["local_usdz_cache"]["validation"]["valid"])
        self.assertEqual(3, scale_stage["local_usdz_cache"]["validation"]["missing_scene_count"])
        blocker_ids = {requirement["id"] for requirement in report["blocking_requirements"]}
        self.assertIn("hf_token_missing", blocker_ids)
        self.assertIn("unsupported_closed_loop_host", blocker_ids)
        self.assertIn("fresh_3scene_cache_invalid", blocker_ids)

    def test_tracked_readiness_snapshot_is_public_safe_and_records_remaining_scale_gap(self) -> None:
        report = json.loads((ROOT / READINESS_RELATIVE).read_text(encoding="utf-8"))
        rendered = json.dumps(report, sort_keys=True)
        stages = {stage["scene_count"]: stage for stage in report["stages"]}

        self.assertEqual("wod2sim_benchmark_regeneration_readiness_v1", report["schema"])
        self.assertTrue(report["no_download_or_rollout_probes"])
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("GPU-", rendered)
        self.assertIn("blocking_requirements", report)
        self.assertIn("next_command_groups", report)
        blocker_ids = {requirement["id"] for requirement in report["blocking_requirements"]}
        self.assertIn("hf_token_missing", blocker_ids)
        self.assertIn("alpasim_base_image_missing", blocker_ids)
        self.assertIn("front_camera_50scene_public2602_cache_invalid", blocker_ids)
        self.assertEqual("verify_claim_gate", report["next_command_groups"][-1]["name"])
        self.assertTrue(stages[10]["public_summary"]["claim_valid"])
        self.assertFalse(stages[50]["local_usdz_cache"]["validation"]["valid"])
        self.assertFalse(stages[50]["public_summary"]["present"])
        self.assertFalse(stages[100]["local_usdz_cache"]["validation"]["valid"])
        self.assertFalse(stages[100]["public_summary"]["present"])


class _DiskUsage:
    total = 500 * 1024**3
    used = 200 * 1024**3
    free = 300 * 1024**3


def _write_usdz(
    path: Path,
    *,
    scene_id: str,
    uuid: str,
    version_string: str = "26.2-test",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "metadata.yaml",
            yaml.safe_dump(
                {
                    "scene_id": scene_id,
                    "uuid": uuid,
                    "version_string": version_string,
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
