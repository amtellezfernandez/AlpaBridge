from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

from minimal_shot_av.cli.commands.run_alpasim_local_external import _resolve_alpasim_root as resolve_run_root
from minimal_shot_av.cli.commands.run_alpasim_local_external import _preflight_scene_artifacts
from minimal_shot_av.cli.commands.run_alpasim_local_external import _preflight_docker_access
from minimal_shot_av.cli.commands.run_alpasim_local_external import _preflight_alpasim_base_image
from minimal_shot_av.cli.commands.run_alpasim_local_external import _validate_alpasim_checkout as validate_run_checkout
from minimal_shot_av.cli.commands.run_alpasim_local_external import (
    MODEL_PRESETS,
    _driver_env,
    _driver_command,
    _preflight_platform_compatibility,
    _wizard_command,
    _wizard_deploy_target,
)
from minimal_shot_av.cli.commands.run_alpasim_local_external import _scene_ids
from minimal_shot_av.cli.commands.setup_alpasim_local_plugin import (
    _apply_local_alpasim_overrides,
    _bootstrap_alpasim_venv,
    _compile_alpasim_protos,
    ALPASIM_CORE_DEPENDENCIES,
    ALPASIM_EDITABLE_PACKAGES,
    _resolve_alpasim_root as resolve_setup_root,
    _validate_alpasim_checkout as validate_setup_checkout,
)


class AlpaSimSetupScriptTests(unittest.TestCase):
    def test_run_launcher_prefers_cli_root_over_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli_root = Path(tmp) / "cli"
            env_root = Path(tmp) / "env"
            cli_root.mkdir()
            env_root.mkdir()
            with patch.dict(os.environ, {"ALPASIM_ROOT": str(env_root)}):
                self.assertEqual(cli_root.resolve(), resolve_run_root(cli_root))

    def test_run_launcher_uses_env_root_when_cli_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_root = Path(tmp) / "env"
            env_root.mkdir()
            with patch.dict(os.environ, {"ALPASIM_ROOT": str(env_root)}, clear=False):
                self.assertEqual(env_root.resolve(), resolve_run_root(None))

    def test_setup_script_uses_env_root_when_cli_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_root = Path(tmp) / "env"
            env_root.mkdir()
            with patch.dict(os.environ, {"ALPASIM_ROOT": str(env_root)}, clear=False):
                self.assertEqual(env_root.resolve(), resolve_setup_root(None))

    def test_checkout_validation_rejects_missing_git_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            (root / "src" / "driver").mkdir(parents=True)
            (root / "src" / "wizard").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='alpasim'\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as run_ctx:
                validate_run_checkout(root)
            self.assertIn("copied directory", str(run_ctx.exception))
            with self.assertRaises(SystemExit) as setup_ctx:
                validate_setup_checkout(root)
            self.assertIn("copied directory", str(setup_ctx.exception))

    def test_checkout_validation_accepts_real_checkout_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            (root / "src" / "driver").mkdir(parents=True)
            (root / "src" / "wizard").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='alpasim'\n", encoding="utf-8")
            (root / ".git").mkdir()
            validate_run_checkout(root)
            validate_setup_checkout(root)

    def test_preflight_rejects_missing_gated_artifacts_without_hf_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            scenes_dir = root / "data" / "scenes"
            all_usdzs_dir = root / "data" / "nre-artifacts" / "all-usdzs"
            scenes_dir.mkdir(parents=True)
            all_usdzs_dir.mkdir(parents=True)
            (scenes_dir / "sim_scenes.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "uuid-1,scene-1,25.7.9,ignored,ignored,huggingface,25.07\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    _preflight_scene_artifacts(alpasim_root=root, scene_ids=["scene-1"])
            self.assertIn("HF_TOKEN is not set", str(ctx.exception))

    def test_preflight_accepts_local_artifacts_without_hf_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            scenes_dir = root / "data" / "scenes"
            all_usdzs_dir = root / "data" / "nre-artifacts" / "all-usdzs"
            scenes_dir.mkdir(parents=True)
            all_usdzs_dir.mkdir(parents=True)
            (scenes_dir / "sim_scenes.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "uuid-1,scene-1,25.7.9,ignored,ignored,huggingface,25.07\n",
                encoding="utf-8",
            )
            (all_usdzs_dir / "uuid-1.usdz").write_text("stub", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                _preflight_scene_artifacts(alpasim_root=root, scene_ids=["scene-1"])

    def test_preflight_docker_access_rejects_socket_permission_denied(self) -> None:
        denied = subprocess.CompletedProcess(
            ["docker", "info"],
            1,
            "",
            "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock",
        )
        with patch("minimal_shot_av.cli.commands.run_alpasim_local_external.subprocess.run", return_value=denied):
            with self.assertRaises(SystemExit) as ctx:
                _preflight_docker_access()
        self.assertIn("Docker daemon is not accessible", str(ctx.exception))

    def test_preflight_docker_access_accepts_healthy_daemon(self) -> None:
        healthy = subprocess.CompletedProcess(["docker", "info"], 0, "", "")
        with patch("minimal_shot_av.cli.commands.run_alpasim_local_external.subprocess.run", return_value=healthy):
            _preflight_docker_access()

    def test_preflight_alpasim_base_image_rejects_missing_image(self) -> None:
        missing = subprocess.CompletedProcess(
            ["docker", "image", "inspect", "alpasim-base:0.66.0"],
            1,
            "",
            "No such image",
        )
        with patch("minimal_shot_av.cli.commands.run_alpasim_local_external.subprocess.run", return_value=missing):
            with self.assertRaises(SystemExit) as ctx:
                _preflight_alpasim_base_image()
        self.assertIn("build_alpasim_base_image.sh", str(ctx.exception))

    def test_preflight_alpasim_base_image_accepts_existing_image(self) -> None:
        present = subprocess.CompletedProcess(
            ["docker", "image", "inspect", "alpasim-base:0.66.0"],
            0,
            "[]",
            "",
        )
        with patch("minimal_shot_av.cli.commands.run_alpasim_local_external.subprocess.run", return_value=present):
            _preflight_alpasim_base_image()

    def test_driver_env_expands_run_dir_and_oracle_actor_proxy(self) -> None:
        env = _driver_env(
            {
                "MSA_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
                "MSA_TOKENBC_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            },
            run_dir=Path("/tmp/run"),
            oracle_actor_proxy=Path("/tmp/oracle.json"),
        )

        self.assertEqual("/tmp/run/driver/selection-log.jsonl", env["MSA_TOKENBC_SELECTION_LOG_PATH"])
        self.assertEqual("/tmp/oracle.json", env["MSA_TOKENBC_ORACLE_ACTOR_PROXY_PATH"])

    def test_actor_axis_preset_requires_oracle_actor_proxy(self) -> None:
        preset = MODEL_PRESETS["token_dagger_iter2_actor_axis_oracle_actor_clamped"]

        self.assertTrue(preset["requires_oracle_actor_proxy"])
        self.assertEqual("actor_axis_constrained", preset["driver_env"]["MSA_TOKENBC_SELECTION_MODE"])
        self.assertEqual("3", preset["driver_env"]["MSA_TOKENBC_HYBRID_TOP_K"])

    def test_direct_actor_planner_preset_requires_oracle_actor_proxy(self) -> None:
        preset = MODEL_PRESETS["direct_actor_planner_oracle"]

        self.assertTrue(preset["requires_oracle_actor_proxy"])
        self.assertFalse(preset["force_cuda"])
        self.assertEqual(
            "{oracle_actor_proxy_path}",
            preset["driver_env"]["MSA_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_PATH"],
        )

    def test_direct_actor_planner_max_clearance_preset_sets_objective(self) -> None:
        preset = MODEL_PRESETS["direct_actor_planner_max_clearance_oracle"]

        self.assertTrue(preset["requires_oracle_actor_proxy"])
        self.assertFalse(preset["force_cuda"])
        self.assertEqual("max_clearance", preset["driver_env"]["MSA_DIRECT_PLANNER_SELECTION_OBJECTIVE"])
        self.assertEqual(
            "{oracle_actor_proxy_path}",
            preset["driver_env"]["MSA_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_PATH"],
        )

    def test_setup_script_applies_repo_tracked_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            source_root = Path(tmp) / "overrides"
            target_file = alpasim_root / "src" / "wizard" / "alpasim_wizard" / "deployment" / "docker_compose.py"
            source_file = source_root / "src" / "wizard" / "alpasim_wizard" / "deployment" / "docker_compose.py"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("override-file\n", encoding="utf-8")

            with patch("minimal_shot_av.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
                _apply_local_alpasim_overrides(alpasim_root)

            self.assertEqual("override-file\n", target_file.read_text(encoding="utf-8"))

    def test_setup_script_also_copies_driver_model_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            source_root = Path(tmp) / "overrides"
            target_file = (
                alpasim_root
                / "src"
                / "driver"
                / "src"
                / "alpasim_driver"
                / "models"
                / "__init__.py"
            )
            source_file = (
                source_root
                / "src"
                / "driver"
                / "src"
                / "alpasim_driver"
                / "models"
                / "__init__.py"
            )
            source_file.parent.mkdir(parents=True)
            source_file.write_text("driver-model-override\n", encoding="utf-8")

            with patch("minimal_shot_av.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
                _apply_local_alpasim_overrides(alpasim_root)

            self.assertEqual("driver-model-override\n", target_file.read_text(encoding="utf-8"))

    def test_setup_script_applies_patch_files_without_copying_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            source_root = Path(tmp) / "overrides"
            target_file = alpasim_root / "patched.txt"
            patch_file = source_root / "route.patch"
            target_file.parent.mkdir(parents=True)
            source_root.mkdir(parents=True)
            target_file.write_text("old\n", encoding="utf-8")
            patch_file.write_text(
                "\n".join(
                    [
                        "diff --git a/patched.txt b/patched.txt",
                        "--- a/patched.txt",
                        "+++ b/patched.txt",
                        "@@ -1 +1 @@",
                        "-old",
                        "+patched",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("minimal_shot_av.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
                _apply_local_alpasim_overrides(alpasim_root)
                _apply_local_alpasim_overrides(alpasim_root)

            self.assertEqual("patched\n", target_file.read_text(encoding="utf-8"))
            self.assertFalse((alpasim_root / "route.patch").exists())

    def test_bootstrap_alpasim_venv_uses_minimal_editable_install_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            for relative in ALPASIM_EDITABLE_PACKAGES:
                (alpasim_root / relative).mkdir(parents=True, exist_ok=True)
            proto_root = alpasim_root / "src" / "grpc" / "alpasim_grpc" / "v0"
            proto_root.mkdir(parents=True, exist_ok=True)
            for name in ("common.proto", "egodriver.proto", "sensorsim.proto"):
                (proto_root / name).write_text("syntax = 'proto3';\n", encoding="utf-8")
            venv_python = alpasim_root / ".venv" / "bin" / "python"
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], *, cwd: Path, capture_output: bool = False):
                calls.append(cmd)
                if cmd[:2] == ["uv", "venv"]:
                    venv_python.parent.mkdir(parents=True, exist_ok=True)
                    venv_python.write_text("", encoding="utf-8")
                if "grpc_tools.protoc" in cmd:
                    output_name = Path(cmd[-1]).stem + "_pb2.py"
                    (proto_root / output_name).write_text("# generated\n", encoding="utf-8")
                return type("Result", (), {"stdout": "", "stderr": "", "returncode": 0})()

            with patch("minimal_shot_av.cli.commands.setup_alpasim_local_plugin._run", side_effect=fake_run):
                _bootstrap_alpasim_venv(alpasim_root, uv_bin="uv")

            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(["uv", "venv", str(alpasim_root / ".venv")], calls[0])
            self.assertIn("pip", calls[1])
            self.assertTrue(set(ALPASIM_CORE_DEPENDENCIES).issubset(set(calls[1])))
            proto_call = next(cmd for cmd in calls if "grpc_tools.protoc" in cmd)
            self.assertEqual(
                [
                    str(venv_python),
                    "-m",
                    "grpc_tools.protoc",
                    f"-I{alpasim_root / 'src' / 'grpc'}",
                    f"--python_out={alpasim_root / 'src' / 'grpc'}",
                    f"--grpc_python_out={alpasim_root / 'src' / 'grpc'}",
                    "alpasim_grpc/v0/common.proto",
                ],
                proto_call,
            )
            editable_targets = [cmd[-1] for cmd in calls if "-e" in cmd]
            self.assertEqual(
                [str(alpasim_root / relative) for relative in ALPASIM_EDITABLE_PACKAGES],
                editable_targets,
            )

    def test_compile_alpasim_protos_runs_from_grpc_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            grpc_root = alpasim_root / "src" / "grpc"
            proto_root = grpc_root / "alpasim_grpc" / "v0"
            proto_root.mkdir(parents=True, exist_ok=True)
            for name in ("common.proto", "egodriver.proto", "sensorsim.proto"):
                (proto_root / name).write_text("syntax = 'proto3';\n", encoding="utf-8")
            calls: list[tuple[list[str], Path]] = []

            def fake_run(cmd: list[str], *, cwd: Path, capture_output: bool = False):
                calls.append((cmd, cwd))
                output_name = Path(cmd[-1]).stem + "_pb2.py"
                (proto_root / output_name).write_text("# generated\n", encoding="utf-8")
                return type("Result", (), {"stdout": "", "stderr": "", "returncode": 0})()

            with patch("minimal_shot_av.cli.commands.setup_alpasim_local_plugin._run", side_effect=fake_run):
                _compile_alpasim_protos(alpasim_root, venv_python=Path("/tmp/alpasim/.venv/bin/python"))

            self.assertEqual(3, len(calls))
            self.assertEqual(
                [
                    str(Path("/tmp/alpasim/.venv/bin/python")),
                    "-m",
                    "grpc_tools.protoc",
                    f"-I{grpc_root}",
                    f"--python_out={grpc_root}",
                    f"--grpc_python_out={grpc_root}",
                    "alpasim_grpc/v0/common.proto",
                ],
                calls[0][0],
            )
            self.assertTrue((proto_root / "common_pb2.py").is_file())
            self.assertTrue((proto_root / "egodriver_pb2.py").is_file())
            self.assertTrue((proto_root / "sensorsim_pb2.py").is_file())

    def test_driver_command_uses_alpasim_venv_python(self) -> None:
        cmd = _driver_command(
            alpasim_python=Path("/tmp/alpasim/.venv/bin/python"),
            driver_config_path=Path("/tmp/run/external-driver-config.yaml"),
        )
        self.assertEqual("/tmp/alpasim/.venv/bin/python", cmd[0])
        self.assertEqual(["-m", "alpasim_driver.main"], cmd[1:3])

    def test_wizard_command_uses_alpasim_venv_binary(self) -> None:
        cmd = _wizard_command(
            alpasim_wizard=Path("/tmp/alpasim/.venv/bin/alpasim_wizard"),
            wizard_driver="spotlight_reflex",
            deploy_target="local_external_driver",
            run_dir=Path("/tmp/run"),
            scene_ids=["scene-1"],
            baseport=6000,
            port=6789,
            timeout=600,
            topology="1gpu",
            dry_run=False,
        )
        self.assertEqual("/tmp/alpasim/.venv/bin/alpasim_wizard", cmd[0])
        self.assertIn("deploy=local_external_driver", cmd)

    def test_wizard_command_can_append_overrides(self) -> None:
        cmd = _wizard_command(
            alpasim_wizard=Path("/tmp/alpasim/.venv/bin/alpasim_wizard"),
            wizard_driver="spotlight_reflex",
            deploy_target="local_external_driver",
            run_dir=Path("/tmp/run"),
            scene_ids=["scene-1"],
            baseport=6000,
            port=6789,
            timeout=600,
            topology="1gpu",
            dry_run=False,
            extra_args=["wizard.timeout=1200"],
        )
        self.assertEqual("wizard.timeout=1200", cmd[-1])

    def test_wizard_deploy_target_uses_arm_profile_on_arm_hosts(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            with patch("platform.machine", return_value="aarch64"):
                self.assertEqual("local_arm_external_driver", _wizard_deploy_target())

    def test_wizard_deploy_target_allows_env_override(self) -> None:
        with patch.dict(os.environ, {"MSA_ALPASIM_DEPLOY_TARGET": "custom_profile"}, clear=False):
            with patch("platform.machine", return_value="x86_64"):
                self.assertEqual("custom_profile", _wizard_deploy_target())

    def test_platform_preflight_rejects_arm_without_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            with patch("platform.machine", return_value="aarch64"):
                with self.assertRaises(SystemExit) as ctx:
                    _preflight_platform_compatibility()
        self.assertIn("amd64-only", str(ctx.exception))

    def test_platform_preflight_allows_arm_with_override(self) -> None:
        with patch.dict(os.environ, {"MSA_ALLOW_UNSUPPORTED_ALPASIM_ARM": "1"}, clear=False):
            with patch("platform.machine", return_value="aarch64"):
                _preflight_platform_compatibility()

    def test_repo_tracked_scene_preset_is_loadable(self) -> None:
        scene_ids = _scene_ids("fresh_3scene", [])
        self.assertEqual(3, len(scene_ids))

    def test_front_camera_30scene_merged_contains_30_scene_ids(self) -> None:
        scene_ids = _scene_ids("front_camera_30scene_merged", [])
        self.assertEqual(30, len(scene_ids))
        self.assertEqual(30, len(set(scene_ids)))
