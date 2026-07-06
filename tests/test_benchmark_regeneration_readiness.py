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
                _write_usdz(
                    cache_dir / f"uuid-{index}.usdz", scene_id=scene_id, uuid=f"uuid-{index}"
                )

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
            stable_report = module.build_readiness_report(
                pilot_preset="fresh_3scene",
                scale_presets=["fresh_3scene"],
                alpasim_root=alpasim_root,
                repo_root=root,
                created_at="2026-07-06",
                env={"HF_TOKEN": "token"},
                command_runner=fake_runner,
                disk_usage=lambda _path: _DiskUsage(),
                stable_public_snapshot=True,
            )

        scale_stage = report["stages"][1]
        self.assertEqual("wod2sim_benchmark_regeneration_readiness_v1", report["schema"])
        self.assertTrue(report["no_download_or_rollout_probes"])
        self.assertTrue(report["readiness"]["all_scale_caches_valid"])
        self.assertTrue(report["readiness"]["closed_loop_runner_ready"])
        self.assertIn("free_bytes", report["disk"])
        self.assertNotIn("free_bytes", stable_report["disk"])
        self.assertTrue(stable_report["disk"]["exact_free_bytes_omitted"])
        self.assertFalse(report["readiness"]["claim_valid_scale_summaries_present"])
        self.assertTrue(scale_stage["local_usdz_cache"]["validation"]["valid"])
        self.assertEqual(3, scale_stage["local_usdz_cache"]["usdz_file_count"])
        self.assertEqual(3, scale_stage["local_usdz_cache"]["matching_scene_count"])
        self.assertEqual(0, scale_stage["local_usdz_cache"]["nonmatching_usdz_file_count"])
        self.assertFalse(scale_stage["public_summary"]["present"])
        self.assertIn(
            "fresh_3scene_claim_summary_missing",
            {requirement["id"] for requirement in report["blocking_requirements"]},
        )
        self.assertEqual("refresh_readiness", report["next_command_groups"][0]["name"])
        self.assertEqual(["readiness"], report["next_command_groups"][0]["command_renderer_groups"])
        self.assertIn(
            "wod2sim-benchmark-readiness",
            report["next_command_groups"][0]["commands"][0]["display"],
        )
        self.assertEqual("refresh_status", report["next_command_groups"][-2]["name"])
        self.assertEqual(["post"], report["next_command_groups"][-2]["command_renderer_groups"])
        self.assertIn("wod2sim-benchmark-status", report["next_command_groups"][-2]["command"])
        self.assertEqual("verify_claim_gate", report["next_command_groups"][-1]["name"])
        self.assertEqual(["post"], report["next_command_groups"][-1]["command_renderer_groups"])
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

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("platform.system", return_value="Linux"),
            patch("platform.machine", return_value="aarch64"),
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

    def test_build_report_can_skip_runtime_probes(self) -> None:
        from wod2sim.cli.commands import benchmark_regeneration_readiness as module

        with tempfile.TemporaryDirectory() as tmp:
            report = module.build_readiness_report(
                pilot_preset="fresh_3scene",
                scale_presets=["fresh_3scene"],
                alpasim_root=Path(tmp) / "alpasim",
                repo_root=Path(tmp),
                created_at="2026-07-06",
                env={"HF_TOKEN": "token"},
                command_runner=lambda argv: (_ for _ in ()).throw(AssertionError(argv)),
                disk_usage=lambda _path: _DiskUsage(),
                skip_runtime_probes=True,
            )

        self.assertTrue(report["runtime_probes_skipped"])
        self.assertEqual("skipped", report["runtime_probes"]["docker_daemon"]["status"])
        self.assertEqual("skipped", report["runtime_probes"]["alpasim_base_image"]["status"])
        self.assertFalse(report["readiness"]["closed_loop_runner_ready"])

    def test_complete_source_cache_makes_cache_link_ready_without_hf_token(self) -> None:
        from wod2sim.cli.commands import benchmark_regeneration_readiness as module
        from wod2sim.cli.commands.run_alpasim_local_external import _scene_ids

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alpasim_root = root / "alpasim"
            source_dir = alpasim_root / "data" / "nre-artifacts" / "all-usdzs"
            source_dir.mkdir(parents=True)
            for index, scene_id in enumerate(_scene_ids("fresh_3scene", []), start=1):
                _write_usdz(
                    source_dir / f"uuid-{index}.usdz", scene_id=scene_id, uuid=f"uuid-{index}"
                )

            report = module.build_readiness_report(
                pilot_preset="fresh_3scene",
                scale_presets=["fresh_3scene"],
                alpasim_root=alpasim_root,
                repo_root=root,
                created_at="2026-07-06",
                env={},
                command_runner=lambda argv: (_ for _ in ()).throw(AssertionError(argv)),
                disk_usage=lambda _path: _DiskUsage(),
                skip_runtime_probes=True,
            )

        scale_stage = report["stages"][1]
        blocker_ids = {requirement["id"] for requirement in report["blocking_requirements"]}
        self.assertTrue(report["readiness"]["source_cache_link_ready"])
        self.assertTrue(report["readiness"]["all_scale_source_caches_valid"])
        self.assertTrue(report["readiness"]["cache_build_ready"])
        self.assertTrue(scale_stage["source_usdz_cache"]["validation"]["valid"])
        self.assertFalse(scale_stage["local_usdz_cache"]["validation"]["valid"])
        self.assertNotIn("hf_token_missing", blocker_ids)
        self.assertIn("fresh_3scene_cache_invalid", blocker_ids)

    def test_tracked_readiness_snapshot_is_public_safe_and_records_remaining_scale_gap(
        self,
    ) -> None:
        report = json.loads((ROOT / READINESS_RELATIVE).read_text(encoding="utf-8"))
        rendered = json.dumps(report, sort_keys=True)
        stages = {stage["scene_count"]: stage for stage in report["stages"]}

        self.assertEqual("wod2sim_benchmark_regeneration_readiness_v1", report["schema"])
        self.assertTrue(report["no_download_or_rollout_probes"])
        self.assertTrue(report["runtime_probes_skipped"])
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("GPU-", rendered)
        self.assertIn("blocking_requirements", report)
        self.assertIn("next_command_groups", report)
        self.assertNotIn("free_bytes", report["disk"])
        self.assertTrue(report["disk"]["exact_free_bytes_omitted"])
        self.assertFalse(report["readiness"]["source_cache_link_ready"])
        self.assertFalse(report["readiness"]["all_scale_source_caches_valid"])
        blocker_ids = {requirement["id"] for requirement in report["blocking_requirements"]}
        self.assertIn("hf_token_missing", blocker_ids)
        self.assertIn("alpasim_base_image_missing", blocker_ids)
        self.assertIn("front_camera_50scene_public2602_cache_invalid", blocker_ids)
        self.assertEqual("refresh_status", report["next_command_groups"][-2]["name"])
        self.assertEqual("verify_claim_gate", report["next_command_groups"][-1]["name"])
        refresh_display = report["next_command_groups"][0]["commands"][0]["display"]
        self.assertIn("--stable-public-snapshot", refresh_display)
        self.assertIn("--skip-runtime-probes", refresh_display)
        build_group = _command_group(report, "build_and_validate_scale_caches")
        self.assertEqual(["cache"], build_group["command_renderer_groups"])
        self.assertEqual(6, len(build_group["commands"]))
        self.assertTrue(
            all(
                "wod2sim-build-local-cache" in command["display"]
                for command in build_group["commands"]
            )
        )
        self.assertTrue(
            any("--source-usdz-dir" in command["display"] for command in build_group["commands"])
        )
        shard_group = _command_group(report, "run_scale_shards_and_promote_summaries")
        self.assertEqual(["shards", "merge", "promote"], shard_group["command_renderer_groups"])
        self.assertEqual(
            [
                {
                    "stage": "workshop_scale",
                    "scene_preset": "front_camera_50scene_public2602",
                    "planned_shards": 5,
                    "minimum_commands": 12,
                },
                {
                    "stage": "stronger_benchmark",
                    "scene_preset": "front_camera_100scene_public2602",
                    "planned_shards": 10,
                    "minimum_commands": 22,
                },
            ],
            shard_group["stage_command_counts"],
        )
        self.assertTrue(stages[10]["public_summary"]["claim_valid"])
        self.assertFalse(stages[50]["local_usdz_cache"]["validation"]["valid"])
        self.assertFalse(stages[50]["source_usdz_cache"]["validation"]["valid"])
        self.assertEqual(0, stages[50]["source_usdz_cache"]["usdz_file_count"])
        self.assertEqual(0, stages[50]["source_usdz_cache"]["matching_scene_count"])
        self.assertEqual(0, stages[50]["source_usdz_cache"]["nonmatching_usdz_file_count"])
        self.assertEqual(0, stages[50]["source_usdz_cache"]["validation"]["present_scene_count"])
        self.assertEqual(50, stages[50]["source_usdz_cache"]["validation"]["missing_scene_count"])
        self.assertFalse(stages[50]["public_summary"]["present"])
        self.assertFalse(stages[100]["local_usdz_cache"]["validation"]["valid"])
        self.assertFalse(stages[100]["source_usdz_cache"]["validation"]["valid"])
        self.assertEqual(0, stages[100]["source_usdz_cache"]["usdz_file_count"])
        self.assertEqual(0, stages[100]["source_usdz_cache"]["matching_scene_count"])
        self.assertEqual(0, stages[100]["source_usdz_cache"]["nonmatching_usdz_file_count"])
        self.assertEqual(0, stages[100]["source_usdz_cache"]["validation"]["present_scene_count"])
        self.assertEqual(100, stages[100]["source_usdz_cache"]["validation"]["missing_scene_count"])
        self.assertFalse(stages[100]["public_summary"]["present"])


class _DiskUsage:
    total = 500 * 1024**3
    used = 200 * 1024**3
    free = 300 * 1024**3


def _command_group(report: dict[str, object], name: str) -> dict[str, object]:
    for group in report["next_command_groups"]:
        if group["name"] == name:
            return group
    raise AssertionError(name)


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
