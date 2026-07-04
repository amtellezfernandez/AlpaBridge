from __future__ import annotations

import argparse
import importlib.util
from unittest import mock
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_alpasim_scene_batch.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_alpasim_scene_batch", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunAlpaSimSceneBatchTests(unittest.TestCase):
    def test_selected_scene_ids_can_slice_preset(self) -> None:
        module = _load_module()
        args = argparse.Namespace(
            scene_preset="front_camera_10scene_smoke",
            scene_id=[],
            scene_offset=2,
            scene_limit=3,
        )

        scene_ids = module._selected_scene_ids(args)

        self.assertEqual(3, len(scene_ids))
        self.assertTrue(all(scene_id.startswith("clipgt-") for scene_id in scene_ids))

    def test_scene_offset_preserves_batch_index_numbering(self) -> None:
        module = _load_module()
        args = argparse.Namespace(
            mode="print",
            model="token_dagger_iter2",
            scene_preset="front_camera_10scene_smoke",
            scene_id=[],
            topology="1gpu",
            timeout=900,
            max_retries=1,
            baseport=6000,
            port=6789,
            wizard_arg=[],
            oracle_actor_proxy=None,
            scene_offset=6,
            scene_limit=None,
        )
        scene_ids = module._selected_scene_ids(args)

        rows = []
        for index, scene_id in enumerate(scene_ids, start=args.scene_offset + 1):
            rows.append((index, scene_id))

        self.assertEqual(7, rows[0][0])

    def test_scene_command_forwards_launcher_options(self) -> None:
        module = _load_module()
        args = argparse.Namespace(
            python="python",
            mode="both",
            model="token_dagger_iter2_hybrid_clamped",
            baseport=6000,
            port=6789,
            timeout=900,
            topology="1gpu",
            driver_warmup_seconds=10.0,
            wizard_dry_run=False,
            checkpoint=None,
            oracle_actor_proxy=None,
            alpasim_root=Path("/tmp/alpasim"),
            wizard_arg=["wizard.timeout=1200"],
            max_retries=1,
        )

        command = module._scene_command(
            args,
            scene_id="clipgt-scene-1",
            run_dir=Path("/tmp/run/001_clipgt-scene-1"),
        )

        self.assertEqual("python", command[0])
        self.assertIn("--scene-id", command)
        self.assertIn("clipgt-scene-1", command)
        self.assertIn("--allow-existing-run-dir", command)
        self.assertIn("--wizard-arg", command)
        self.assertEqual("wizard.timeout=1200", command[-1])
        self.assertEqual("/tmp/alpasim", command[command.index("--alpasim-root") + 1])

    def test_scene_command_forwards_oracle_actor_proxy(self) -> None:
        module = _load_module()
        args = argparse.Namespace(
            python="python",
            mode="both",
            model="token_dagger_iter2_axis_constrained_oracle_actor_clamped",
            baseport=6000,
            port=6789,
            timeout=900,
            topology="1gpu",
            driver_warmup_seconds=10.0,
            wizard_dry_run=False,
            checkpoint=None,
            oracle_actor_proxy=Path("/tmp/oracle_actor_proxy.json"),
            alpasim_root=None,
            wizard_arg=[],
            max_retries=1,
        )

        command = module._scene_command(
            args,
            scene_id="clipgt-scene-1",
            run_dir=Path("/tmp/run/001_clipgt-scene-1"),
        )

        self.assertEqual(
            "/tmp/oracle_actor_proxy.json",
            command[command.index("--oracle-actor-proxy") + 1],
        )

    def test_scene_status_detects_completed_partial_and_missing(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing"
            partial = root / "partial"
            partial.mkdir()
            completed = root / "completed" / "aggregate"
            completed.mkdir(parents=True)
            (completed / "metrics_unprocessed.parquet").write_text("", encoding="utf-8")
            completed_alt = root / "completed_alt" / "aggregate"
            completed_alt.mkdir(parents=True)
            (completed_alt / "metrics_results.txt").write_text("", encoding="utf-8")

            self.assertEqual("missing", module._scene_status(missing))
            self.assertEqual("partial", module._scene_status(partial))
            self.assertEqual("completed", module._scene_status(completed.parent))
            self.assertEqual("completed", module._scene_status(completed_alt.parent))

    def test_run_scene_with_retries_retries_once_then_succeeds(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            command = ["python", "scene.py", "--run-dir", str(run_dir)]
            results = [1, 0]

            def _fake_run(args, **_kwargs):
                if args[:3] == ["docker", "compose", "-f"]:
                    return argparse.Namespace(returncode=0)
                if results[0] == 0:
                    aggregate = run_dir / "aggregate"
                    aggregate.mkdir(exist_ok=True)
                    (aggregate / "metrics_results.txt").write_text("ok\n", encoding="utf-8")
                return argparse.Namespace(returncode=results.pop(0))

            with mock.patch.object(module.subprocess, "run", side_effect=_fake_run) as patched:
                returncode, attempts = module._run_scene_with_retries(
                    command,
                    cwd=ROOT,
                    max_retries=1,
                )

        self.assertEqual(0, returncode)
        self.assertEqual(2, attempts)
        self.assertEqual(2, len([call for call in patched.call_args_list if call.args[0][0] == "python"]))

    def test_run_scene_with_retries_cleans_up_after_failure(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
            command = [
                "python",
                "scene.py",
                "--run-dir",
                str(run_dir),
            ]
            results = [1, 0]

            def _fake_run(args, **_kwargs):
                if args[:3] == ["docker", "compose", "-f"]:
                    return argparse.Namespace(returncode=0)
                if results[0] == 0:
                    aggregate = run_dir / "aggregate"
                    aggregate.mkdir(exist_ok=True)
                    (aggregate / "metrics_results.txt").write_text("ok\n", encoding="utf-8")
                return argparse.Namespace(returncode=results.pop(0))

            with mock.patch.object(module.subprocess, "run", side_effect=_fake_run) as patched:
                returncode, attempts = module._run_scene_with_retries(
                    command,
                    cwd=ROOT,
                    max_retries=1,
                )

        self.assertEqual(0, returncode)
        self.assertEqual(2, attempts)
        docker_calls = [call for call in patched.call_args_list if call.args[0][:2] == ["docker", "compose"]]
        self.assertEqual(1, len(docker_calls))

    def test_run_scene_with_retries_requires_completed_artifacts(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
            command = [
                "python",
                "scene.py",
                "--run-dir",
                str(run_dir),
            ]
            results = [0, 0]

            def _fake_run(args, **_kwargs):
                if args[:3] == ["docker", "compose", "-f"]:
                    aggregate = run_dir / "aggregate"
                    aggregate.mkdir(exist_ok=True)
                    (aggregate / "metrics_results.txt").write_text("ok\n", encoding="utf-8")
                    return argparse.Namespace(returncode=0)
                return argparse.Namespace(returncode=results.pop(0))

            with mock.patch.object(module.subprocess, "run", side_effect=_fake_run) as patched:
                returncode, attempts = module._run_scene_with_retries(
                    command,
                    cwd=ROOT,
                    max_retries=1,
                )

        self.assertEqual(0, returncode)
        self.assertEqual(2, attempts)
        docker_calls = [call for call in patched.call_args_list if call.args[0][:2] == ["docker", "compose"]]
        self.assertEqual(1, len(docker_calls))


if __name__ == "__main__":
    unittest.main()
