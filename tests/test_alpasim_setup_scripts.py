from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import alpabridge.cli.commands.run_alpasim_local_external as launch_cmd
import alpabridge.cli.commands.setup_alpasim_local_plugin as setup_cmd
from alpabridge.cli.commands.run_alpasim_local_external import (
    MODEL_PRESETS,
    PUBLIC_RELEASE_MODELS,
    _aggregate_status,
    _complete_run_status,
    _driver_command,
    _driver_env,
    _local_usdz_dir_from_wizard_args,
    _planned_run_status,
    _preflight_alpasim_base_image,
    _preflight_alpasim_local_environment,
    _preflight_camera_rig_compatibility,
    _preflight_docker_access,
    _preflight_platform_compatibility,
    _preflight_scene_artifacts,
    _scene_catalog_paths,
    _scene_ids,
    _wizard_command,
    _wizard_deploy_target,
    _write_run_status,
)
from alpabridge.cli.commands.run_alpasim_local_external import (
    _build_parser as build_run_parser,
)
from alpabridge.cli.commands.run_alpasim_local_external import (
    _resolve_alpasim_root as resolve_run_root,
)
from alpabridge.cli.commands.run_alpasim_local_external import (
    _validate_alpasim_checkout as validate_run_checkout,
)
from alpabridge.cli.commands.run_alpasim_scene_batch import _build_parser as build_batch_parser
from alpabridge.cli.commands.setup_alpasim_local_plugin import (
    ALPASIM_CORE_DEPENDENCIES,
    ALPASIM_EDITABLE_PACKAGES,
    _apply_alpasim_patch,
    _apply_local_alpasim_overrides,
    _bootstrap_alpasim_venv,
    _compile_alpasim_protos,
    _install_torch_for_alpasim,
    _patch_effectively_present,
    _should_copy_override_path,
)
from alpabridge.cli.commands.setup_alpasim_local_plugin import (
    _resolve_alpasim_root as resolve_setup_root,
)
from alpabridge.cli.commands.setup_alpasim_local_plugin import (
    _validate_alpasim_checkout as validate_setup_checkout,
)


class AlpaSimSetupScriptTests(unittest.TestCase):
    def _load_override_docker_compose_module(self, override_path: Path):
        fake_modules = {
            "alpasim_utils": types.ModuleType("alpasim_utils"),
            "alpasim_utils.paths": types.ModuleType("alpasim_utils.paths"),
            "fakepkg": types.ModuleType("fakepkg"),
            "fakepkg.context": types.ModuleType("fakepkg.context"),
            "fakepkg.services": types.ModuleType("fakepkg.services"),
            "fakepkg.utils": types.ModuleType("fakepkg.utils"),
        }
        fake_modules["alpasim_utils.paths"].find_repo_root = lambda _path: ROOT
        fake_modules["fakepkg.context"].WizardContext = object
        fake_modules["fakepkg.services"].ContainerDefinition = object
        fake_modules["fakepkg.services"].build_container_set = lambda *args, **kwargs: None
        fake_modules["fakepkg.utils"].LiteralStr = str
        fake_modules["fakepkg.utils"].write_yaml = lambda *args, **kwargs: None

        spec = importlib.util.spec_from_file_location(
            "fakepkg.deployment.docker_compose",
            override_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(override_path)
        module = importlib.util.module_from_spec(spec)
        module.__package__ = "fakepkg.deployment"
        with patch.dict(sys.modules, fake_modules, clear=False):
            spec.loader.exec_module(module)
        return module

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

    def test_setup_check_only_does_not_bootstrap_or_install(self) -> None:
        args = argparse.Namespace(
            alpasim_root=Path("/tmp/alpasim"),
            check_only=True,
            skip_overrides=False,
        )
        with patch.object(setup_cmd, "_parse_args", return_value=args), patch.object(
            setup_cmd, "_validate_alpasim_checkout"
        ), patch.object(
            setup_cmd,
            "_plugin_registry_snapshot",
            return_value={"loaded": [{"name": name} for name in setup_cmd.REQUIRED_MODELS], "failures": []},
        ), patch.object(
            setup_cmd, "_fail_on_duplicate_public_model_entry_points"
        ), patch.object(
            setup_cmd, "_apply_local_alpasim_overrides"
        ) as apply_overrides, patch.object(
            setup_cmd, "_bootstrap_alpasim_venv"
        ) as bootstrap, patch.object(
            setup_cmd, "_run"
        ) as run_install, patch.object(
            setup_cmd, "_resolve_alpasim_root", return_value=Path("/tmp/alpasim")
        ):
            with patch.object(Path, "is_file", return_value=True), patch.object(Path, "is_dir", return_value=True):
                setup_cmd.main()

        apply_overrides.assert_not_called()
        bootstrap.assert_not_called()
        run_install.assert_not_called()

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

    def test_preflight_rejects_missing_local_alpasim_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"

            with self.assertRaises(SystemExit) as ctx:
                _preflight_alpasim_local_environment(root)

        message = str(ctx.exception)
        self.assertIn(".venv/bin/python", message)
        self.assertIn(".venv/bin/alpasim_wizard", message)
        self.assertIn("bootstrap_alpasim_env.sh", message)

    def test_preflight_accepts_local_alpasim_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            bin_dir = root / ".venv" / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").write_text("", encoding="utf-8")
            (bin_dir / "alpasim_wizard").write_text("", encoding="utf-8")

            _preflight_alpasim_local_environment(root)

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

    def test_camera_rig_check_skips_when_no_ego_hoods_dir_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            root.mkdir()

            _preflight_camera_rig_compatibility(alpasim_root=root)

    def test_camera_rig_check_accepts_when_every_requested_camera_has_a_mask(self) -> None:
        # The shipped presets all request camera_front_wide_120fov; a rig that
        # defines a mask for it must pass with no error.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            rig_dir = root / "data" / "nre-artifacts" / "ego-hoods" / "hyperion_8_1"
            rig_dir.mkdir(parents=True)
            (rig_dir / "camera_front_wide_120fov.png").write_bytes(b"stub")

            _preflight_camera_rig_compatibility(alpasim_root=root)

    def test_camera_rig_check_rejects_when_no_local_rig_has_the_requested_camera(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            rig_dir = root / "data" / "nre-artifacts" / "ego-hoods" / "hyperion_8_1"
            rig_dir.mkdir(parents=True)
            (rig_dir / "camera_rear_wide_60fov.png").write_bytes(b"stub")

            with self.assertRaises(SystemExit) as ctx:
                _preflight_camera_rig_compatibility(
                    alpasim_root=root, models=("constant_velocity",)
                )

        message = str(ctx.exception)
        self.assertIn("constant_velocity", message)
        self.assertIn("camera_front_wide_120fov", message)
        self.assertIn("hyperion_8_1", message)
        self.assertIn("AlpaSim ego-vehicle rig asset limitation", message)

    def test_preflight_accepts_explicit_local_usdz_dir_without_hf_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            scenes_dir = root / "data" / "scenes"
            local_usdz_dir = Path(tmp) / "local-usdzs"
            scenes_dir.mkdir(parents=True)
            local_usdz_dir.mkdir()
            (scenes_dir / "sim_scenes.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "uuid-1,scene-1,26.1.112,ignored,ignored,huggingface,26.02\n",
                encoding="utf-8",
            )
            (local_usdz_dir / "uuid-1.usdz").write_text("stub", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                _preflight_scene_artifacts(
                    alpasim_root=root,
                    scene_ids=["scene-1"],
                    local_usdz_dir=local_usdz_dir,
                )

    def test_preflight_accepts_manifest_remapped_local_usdz_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            scenes_dir = root / "data" / "scenes"
            local_usdz_dir = Path(tmp) / "local-usdzs"
            scenes_dir.mkdir(parents=True)
            local_usdz_dir.mkdir()
            (scenes_dir / "sim_scenes.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "catalog-uuid,scene-1,26.1.112,ignored,ignored,huggingface,26.02\n",
                encoding="utf-8",
            )
            (local_usdz_dir / "local-uuid.usdz").write_text("stub", encoding="utf-8")
            (local_usdz_dir / "alpabridge-local-usdz-cache-manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "alpabridge_local_usdz_cache_manifest_v1",
                        "scenes": [
                            {
                                "scene_id": "scene-1",
                                "uuid": "local-uuid",
                                "catalog_uuid": "catalog-uuid",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                _preflight_scene_artifacts(
                    alpasim_root=root,
                    scene_ids=["scene-1"],
                    local_usdz_dir=local_usdz_dir,
                )

    def test_preflight_rejects_incomplete_explicit_local_usdz_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            scenes_dir = root / "data" / "scenes"
            local_usdz_dir = Path(tmp) / "local-usdzs"
            scenes_dir.mkdir(parents=True)
            local_usdz_dir.mkdir()
            (scenes_dir / "sim_scenes.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "uuid-1,scene-1,26.1.112,ignored,ignored,huggingface,26.02\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    _preflight_scene_artifacts(
                        alpasim_root=root,
                        scene_ids=["scene-1"],
                        local_usdz_dir=local_usdz_dir,
                    )

        message = str(ctx.exception)
        self.assertIn("scenes.local_usdz_dir", message)
        self.assertIn("scene-1:uuid-1", message)

    def test_local_usdz_dir_from_wizard_args_uses_last_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"

            local_usdz_dir = _local_usdz_dir_from_wizard_args(
                [
                    f"scenes.local_usdz_dir={first}",
                    "eval.video.render_video=false",
                    f"+scenes.local_usdz_dir='{second}'",
                ]
            )

        self.assertEqual(second.resolve(), local_usdz_dir)

    def test_local_usdz_dir_from_wizard_args_can_resolve_from_alpasim_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            local_usdz_dir = alpasim_root / "data" / "nre-artifacts" / "local-usdzs"
            local_usdz_dir.mkdir(parents=True)

            resolved = _local_usdz_dir_from_wizard_args(
                ["scenes.local_usdz_dir=data/nre-artifacts/local-usdzs"],
                base_dir=alpasim_root,
            )

        self.assertEqual(local_usdz_dir.resolve(), resolved)

    def test_scene_catalog_paths_can_use_public_2602_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"

            paths = _scene_catalog_paths("front_camera_50scene_public2602", alpasim_root)

        self.assertEqual([alpasim_root / "data" / "scenes" / "sim_scenes_2602.csv"], paths)

    def test_preflight_uses_requested_scene_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"
            scenes_dir = root / "data" / "scenes"
            all_usdzs_dir = root / "data" / "nre-artifacts" / "all-usdzs"
            scenes_dir.mkdir(parents=True)
            all_usdzs_dir.mkdir(parents=True)
            (scenes_dir / "sim_scenes.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "old-uuid,scene-2602,25.7.9,ignored,ignored,huggingface,25.07\n",
                encoding="utf-8",
            )
            (scenes_dir / "sim_scenes_2602.csv").write_text(
                "uuid,scene_id,nre_version_string,path,last_modified,artifact_repository,hf_revision\n"
                "new-uuid,scene-2602,26.1.112,ignored,ignored,huggingface,26.02\n",
                encoding="utf-8",
            )
            (all_usdzs_dir / "new-uuid.usdz").write_text("stub", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                _preflight_scene_artifacts(
                    alpasim_root=root,
                    scene_ids=["scene-2602"],
                    scene_catalog_paths=[scenes_dir / "sim_scenes_2602.csv"],
                )

    def test_preflight_rejects_missing_requested_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "alpasim"

            with self.assertRaises(SystemExit) as ctx:
                _preflight_scene_artifacts(
                    alpasim_root=root,
                    scene_ids=["scene-1"],
                    scene_catalog_paths=[root / "data" / "scenes" / "missing.csv"],
                )

        self.assertIn("scene catalog files are missing", str(ctx.exception))

    def test_preflight_docker_access_rejects_socket_permission_denied(self) -> None:
        denied = subprocess.CompletedProcess(
            ["docker", "info"],
            1,
            "",
            "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock",
        )
        with patch("alpabridge.cli.commands.run_alpasim_local_external.subprocess.run", return_value=denied):
            with self.assertRaises(SystemExit) as ctx:
                _preflight_docker_access()
        self.assertIn("Docker daemon is not accessible", str(ctx.exception))

    def test_preflight_docker_access_accepts_healthy_daemon(self) -> None:
        healthy = subprocess.CompletedProcess(["docker", "info"], 0, "", "")
        with patch("alpabridge.cli.commands.run_alpasim_local_external.subprocess.run", return_value=healthy):
            _preflight_docker_access()

    def test_preflight_alpasim_base_image_rejects_missing_image(self) -> None:
        missing = subprocess.CompletedProcess(
            ["docker", "image", "inspect", "alpasim-base:0.66.0"],
            1,
            "",
            "No such image",
        )
        with patch("alpabridge.cli.commands.run_alpasim_local_external.subprocess.run", return_value=missing):
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
        with patch("alpabridge.cli.commands.run_alpasim_local_external.subprocess.run", return_value=present):
            _preflight_alpasim_base_image()

    def test_install_torch_for_alpasim_uses_pip_directly(self) -> None:
        with patch(
            "alpabridge.cli.commands.setup_alpasim_local_plugin._ensure_venv_pip"
        ) as ensure_pip, patch(
            "alpabridge.cli.commands.setup_alpasim_local_plugin._run"
        ) as run:
            run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            _install_torch_for_alpasim(
                uv_bin="/usr/bin/uv",
                venv_python=Path("/tmp/alpasim/.venv/bin/python"),
                cwd=Path("/tmp/alpasim"),
            )

        ensure_pip.assert_called_once_with(
            venv_python=Path("/tmp/alpasim/.venv/bin/python"),
            cwd=Path("/tmp/alpasim"),
        )
        self.assertEqual(run.call_count, 2)
        install_call, verify_call = run.call_args_list
        self.assertEqual(
            install_call.args[0],
            [
                "/tmp/alpasim/.venv/bin/python",
                "-m",
                "pip",
                "install",
                "--index-url",
                setup_cmd.TORCH_INDEX_URL,
                setup_cmd.TORCH_PACKAGE,
                "torchvision",
            ],
        )
        self.assertEqual(install_call.kwargs["cwd"], Path("/tmp/alpasim"))
        self.assertEqual(
            verify_call.args[0],
            ["/tmp/alpasim/.venv/bin/python", "-c", "import torchvision"],
        )
        self.assertEqual(verify_call.kwargs["cwd"], Path("/tmp/alpasim"))
        self.assertTrue(verify_call.kwargs.get("capture_output"))

    def test_install_torch_for_alpasim_fails_fast_on_torchvision_mismatch(self) -> None:
        # `_run` itself raises `SystemExit(returncode)` on a nonzero exit (after
        # writing stdout/stderr) -- simulate that same contract for the second
        # (verification) call to prove a torchvision import failure propagates
        # instead of being swallowed.
        with patch("alpabridge.cli.commands.setup_alpasim_local_plugin._ensure_venv_pip") as ensure_pip, patch(
            "alpabridge.cli.commands.setup_alpasim_local_plugin._run"
        ) as run:
            run.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
                SystemExit(1),
            ]
            with self.assertRaises(SystemExit) as ctx:
                _install_torch_for_alpasim(
                    uv_bin="/usr/bin/uv",
                    venv_python=Path("/tmp/alpasim/.venv/bin/python"),
                    cwd=Path("/tmp/alpasim"),
                )
        self.assertEqual(ctx.exception.code, 1)
        ensure_pip.assert_called_once()
        self.assertEqual(run.call_count, 2)

    def test_driver_env_expands_run_dir_and_oracle_actor_proxy(self) -> None:
        env = _driver_env(
            {
                "ALPABRIDGE_TOKENBC_SELECTION_LOG_PATH": "{run_dir}/driver/selection-log.jsonl",
                "ALPABRIDGE_TOKENBC_ORACLE_ACTOR_PROXY_PATH": "{oracle_actor_proxy_path}",
            },
            run_dir=Path("/tmp/run"),
            oracle_actor_proxy=Path("/tmp/oracle.json"),
        )

        self.assertEqual("/tmp/run/driver/selection-log.jsonl", env["ALPABRIDGE_TOKENBC_SELECTION_LOG_PATH"])
        self.assertEqual("/tmp/oracle.json", env["ALPABRIDGE_TOKENBC_ORACLE_ACTOR_PROXY_PATH"])

    def test_direct_actor_planner_preset_requires_oracle_actor_proxy(self) -> None:
        preset = MODEL_PRESETS["direct_actor_planner"]

        self.assertTrue(preset["requires_oracle_actor_proxy"])
        self.assertFalse(preset["force_cuda"])
        self.assertEqual(
            "{oracle_actor_proxy_path}",
            preset["driver_env"]["ALPABRIDGE_DIRECT_PLANNER_ORACLE_ACTOR_PROXY_PATH"],
        )

    def test_dependency_light_baseline_presets_need_no_private_artifacts(self) -> None:
        for model_name in ("constant_velocity", "route_following"):
            preset = MODEL_PRESETS[model_name]
            self.assertFalse(preset.get("checkpoint_required", False))
            self.assertFalse(preset.get("requires_oracle_actor_proxy", False))
            self.assertFalse(preset["force_cuda"])
            self.assertEqual(
                "{run_dir}/driver/baseline-log.jsonl",
                preset["driver_env"]["ALPABRIDGE_BASELINE_LOG_PATH"],
            )

    def test_public_release_models_match_curated_surface(self) -> None:
        self.assertEqual(
            ("constant_velocity", "route_following", "token_dagger_bc", "direct_actor_planner"),
            PUBLIC_RELEASE_MODELS,
        )

    def test_model_presets_export_only_public_release_surface(self) -> None:
        self.assertEqual(PUBLIC_RELEASE_MODELS, tuple(MODEL_PRESETS))
        private_catalog_attr = "_ALL" "_MODEL_PRESETS"
        self.assertFalse(hasattr(launch_cmd, private_catalog_attr))

    def test_public_release_models_emit_driver_logs_by_default(self) -> None:
        self.assertEqual(
            "{run_dir}/driver/selection-log.jsonl",
            MODEL_PRESETS["token_dagger_bc"]["driver_env"]["ALPABRIDGE_TOKENBC_SELECTION_LOG_PATH"],
        )
        self.assertEqual(
            "{run_dir}/driver/direct-planner-log.jsonl",
            MODEL_PRESETS["direct_actor_planner"]["driver_env"]["ALPABRIDGE_DIRECT_PLANNER_LOG_PATH"],
        )

    def test_planned_run_status_starts_as_planned(self) -> None:
        args = argparse.Namespace(
            mode="print",
            model="token_dagger_bc",
            scene_preset="fresh_3scene",
            scene_id=[],
        )

        status = _planned_run_status(
            args=args,
            run_dir=Path("/tmp/run"),
            driver_config_path=Path("/tmp/run/external-driver-config.yaml"),
            checkpoint=None,
            oracle_actor_proxy=None,
        )

        self.assertEqual("alpabridge_run_status_v1", status["schema"])
        self.assertEqual("planned", status["state"])
        self.assertEqual("planned", status["phase"])
        self.assertEqual("missing", status["aggregate_status"])
        self.assertEqual("/tmp/run/driver.stdout.log", status["driver_stdout_log"])

    def test_wizard_command_includes_scene_catalog_override(self) -> None:
        command = _wizard_command(
            alpasim_wizard=Path("/tmp/alpasim/.venv/bin/alpasim_wizard"),
            wizard_driver="token_dagger_bc",
            deploy_target="deploy.local",
            run_dir=Path("/tmp/run"),
            scene_ids=["scene-1"],
            baseport=6000,
            port=6789,
            timeout=900,
            topology="1gpu",
            dry_run=False,
            scene_catalog_paths=[Path("/tmp/alpasim/data/scenes/sim_scenes_2602.csv")],
        )

        self.assertIn('scenes.scenes_csv=["/tmp/alpasim/data/scenes/sim_scenes_2602.csv"]', command)

    def test_complete_run_status_writes_lifecycle_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            status_path = run_dir / "run-status.json"
            args = argparse.Namespace(
                mode="both",
                model="token_dagger_bc",
                scene_preset="fresh_3scene",
                scene_id=[],
            )
            status = _planned_run_status(
                args=args,
                run_dir=run_dir,
                driver_config_path=run_dir / "external-driver-config.yaml",
                checkpoint=None,
                oracle_actor_proxy=None,
            )
            _write_run_status(status_path, status)
            aggregate_dir = run_dir / "aggregate"
            aggregate_dir.mkdir()
            (aggregate_dir / "metrics_results.txt").write_text("ok\n", encoding="utf-8")

            _complete_run_status(
                status_path,
                status,
                phase="both",
                state="completed",
                driver_returncode=-15,
                wizard_returncode=0,
                aggregate_status=_aggregate_status(run_dir),
            )
            payload = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual("completed", payload["state"])
        self.assertEqual("both", payload["phase"])
        self.assertEqual(-15, payload["driver_returncode"])
        self.assertEqual(0, payload["wizard_returncode"])
        self.assertEqual("completed", payload["aggregate_status"])
        self.assertIsNotNone(payload["completed_at"])

    def test_source_tree_launch_wrapper_hides_non_public_preset_catalog(self) -> None:
        script_path = ROOT / "scripts" / "run_alpasim_local_external.py"
        spec = importlib.util.spec_from_file_location("alpabridge_launch_script", script_path)
        if spec is None or spec.loader is None:
            raise ImportError(script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(PUBLIC_RELEASE_MODELS, tuple(module.MODEL_PRESETS))
        private_catalog_attr = "_ALL" "_MODEL_PRESETS"
        self.assertFalse(hasattr(module, private_catalog_attr))

    def test_launch_parser_only_exposes_public_release_models(self) -> None:
        parser = build_run_parser()
        model_action = next(action for action in parser._actions if action.dest == "model")

        self.assertEqual("token_dagger_bc", parser.get_default("model"))
        self.assertEqual(PUBLIC_RELEASE_MODELS, model_action.choices)

    def test_print_mode_skips_live_runtime_and_scene_artifact_preflights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            run_dir = Path(tmp) / "run"
            (alpasim_root / "src" / "driver").mkdir(parents=True)
            (alpasim_root / "src" / "wizard").mkdir(parents=True)
            (alpasim_root / ".venv" / "bin").mkdir(parents=True)
            (alpasim_root / "pyproject.toml").write_text("[project]\nname='alpasim'\n", encoding="utf-8")
            (alpasim_root / ".git").mkdir()
            (alpasim_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (alpasim_root / ".venv" / "bin" / "alpasim_wizard").write_text("", encoding="utf-8")
            checkpoint = Path(tmp) / "token_dagger_bc.pt"
            checkpoint.write_bytes(b"command-materialization-smoke")
            args = argparse.Namespace(
                mode="print",
                model="token_dagger_bc",
                checkpoint=checkpoint,
                oracle_actor_proxy=None,
                scene_preset="fresh_3scene",
                scene_id=[],
                run_dir=run_dir,
                runs_root=Path(tmp) / "runs",
                alpasim_root=alpasim_root,
                port=6789,
                baseport=6000,
                timeout=600,
                topology="1gpu",
                wizard_dry_run=False,
                wizard_arg=[],
                driver_warmup_seconds=10.0,
                allow_existing_run_dir=False,
            )

            with patch.object(launch_cmd, "_parse_args", return_value=args), patch.object(
                launch_cmd, "_preflight_platform_compatibility"
            ), patch.object(
                launch_cmd, "_preflight_docker_access", side_effect=AssertionError("docker preflight should be skipped")
            ), patch.object(
                launch_cmd, "_preflight_alpasim_base_image", side_effect=AssertionError("image preflight should be skipped")
            ), patch.object(
                launch_cmd, "_preflight_nvidia_container_runtime", side_effect=AssertionError("gpu preflight should be skipped")
            ), patch.object(
                launch_cmd, "_preflight_scene_artifacts", side_effect=AssertionError("scene artifact preflight should be skipped")
            ), patch(
                "sys.stdout", new_callable=StringIO
            ):
                launch_cmd.main()

            self.assertTrue((run_dir / "launch-metadata.json").is_file())
            metadata = json.loads((run_dir / "launch-metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(str(alpasim_root.resolve()), metadata["provenance"]["alpasim_checkout"]["root"])
            self.assertIn("git_commit", metadata["provenance"]["alpasim_checkout"])
            self.assertEqual("alpasim-base:0.66.0", metadata["provenance"]["docker_image"]["tag"])
            self.assertIn("present", metadata["provenance"]["docker_image"])
            self.assertTrue((run_dir / "driver-command.sh").is_file())
            self.assertTrue((run_dir / "wizard-command.sh").is_file())
            self.assertTrue((run_dir / "run-status.json").is_file())

    def test_batch_parser_only_exposes_public_release_models(self) -> None:
        parser = build_batch_parser()
        model_action = next(action for action in parser._actions if action.dest == "model")

        self.assertEqual(PUBLIC_RELEASE_MODELS, model_action.choices)

    def test_setup_script_applies_repo_tracked_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            source_root = Path(tmp) / "overrides"
            target_file = alpasim_root / "src" / "wizard" / "alpasim_wizard" / "deployment" / "docker_compose.py"
            source_file = source_root / "src" / "wizard" / "alpasim_wizard" / "deployment" / "docker_compose.py"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("override-file\n", encoding="utf-8")

            with patch("alpabridge.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
                _apply_local_alpasim_overrides(alpasim_root)

            self.assertEqual("override-file\n", target_file.read_text(encoding="utf-8"))

    def test_runtime_override_rewrites_single_run_array_job_dir_to_log_dir(self) -> None:
        override_path = (
            ROOT
            / "src"
            / "alpabridge"
            / "alpasim_overrides"
            / "src"
            / "wizard"
            / "alpasim_wizard"
            / "deployment"
            / "docker_compose.py"
        )
        module = self._load_override_docker_compose_module(override_path)

        command = (
            "uv run python -m alpasim_runtime.simulate "
            "--log-dir=/mnt/log_dir --array-job-dir=/mnt/array_job_dir"
        )
        volumes = [
            "/tmp/run:/mnt/log_dir",
            "/tmp/run:/mnt/array_job_dir",
        ]

        normalized = module._normalize_single_run_runtime_command(command, volumes)

        self.assertIn("--array-job-dir=/mnt/log_dir", normalized)
        self.assertNotIn("--array-job-dir=/mnt/array_job_dir", normalized)

    def test_packaged_and_tracked_docker_compose_overrides_stay_in_sync(self) -> None:
        packaged = (
            ROOT
            / "src"
            / "alpabridge"
            / "alpasim_overrides"
            / "src"
            / "wizard"
            / "alpasim_wizard"
            / "deployment"
            / "docker_compose.py"
        )
        tracked = (
            ROOT
            / "third_party"
            / "alpasim_overrides"
            / "src"
            / "wizard"
            / "alpasim_wizard"
            / "deployment"
            / "docker_compose.py"
        )

        self.assertEqual(
            packaged.read_text(encoding="utf-8"),
            tracked.read_text(encoding="utf-8"),
        )

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

            with patch("alpabridge.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
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

            with patch("alpabridge.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
                _apply_local_alpasim_overrides(alpasim_root)
                _apply_local_alpasim_overrides(alpasim_root)

            self.assertEqual("patched\n", target_file.read_text(encoding="utf-8"))
            self.assertFalse((alpasim_root / "route.patch").exists())

    def test_setup_script_skips_python_cache_artifacts_in_override_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            source_root = Path(tmp) / "overrides"
            source_root.mkdir(parents=True)
            tracked_file = source_root / "src" / "wizard" / "alpasim_wizard" / "deployment" / "docker_compose.py"
            pycache_file = (
                source_root
                / "src"
                / "wizard"
                / "alpasim_wizard"
                / "deployment"
                / "__pycache__"
                / "docker_compose.cpython-312.pyc"
            )
            tracked_file.parent.mkdir(parents=True, exist_ok=True)
            pycache_file.parent.mkdir(parents=True, exist_ok=True)
            tracked_file.write_text("print('tracked')\n", encoding="utf-8")
            pycache_file.write_bytes(b"compiled")

            with patch("alpabridge.cli.commands.setup_alpasim_local_plugin.ALPASIM_OVERRIDE_ROOT", source_root):
                _apply_local_alpasim_overrides(alpasim_root)

            self.assertTrue((alpasim_root / tracked_file.relative_to(source_root)).is_file())
            self.assertFalse((alpasim_root / pycache_file.relative_to(source_root)).exists())

    def test_should_copy_override_path_rejects_generated_python_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "overrides"
            pycache_file = root / "src" / "__pycache__" / "foo.pyc"
            pyc_file = root / "src" / "module.pyc"
            pyo_file = root / "src" / "module.pyo"
            patch_file = root / "src" / "route.patch"
            tracked_file = root / "src" / "module.py"
            for path in (pycache_file, pyc_file, pyo_file, patch_file, tracked_file):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x\n", encoding="utf-8")

            self.assertFalse(_should_copy_override_path(pycache_file))
            self.assertFalse(_should_copy_override_path(pyc_file))
            self.assertFalse(_should_copy_override_path(pyo_file))
            self.assertFalse(_should_copy_override_path(patch_file))
            self.assertTrue(_should_copy_override_path(tracked_file))

    def test_patch_effectively_present_detects_local_checkout_override_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            files = {
                "Dockerfile": 'if [ "${TARGETARCH}" = "arm64" ]; then\nuv pip install --python /repo/.venv/bin/python\n',
                "pyproject.toml": 'docker_local = [\n  "alpasim_controller",\n  "alpasim-runtime",\n]\n',
                "src/driver/src/alpasim_driver/main.py": "\n".join(
                    [
                        "close_session for unknown session %s; treating as idempotent",
                        "submit_image_observation for unknown session %s at %s; ignoring late frame",
                        "submit_egomotion_observation for unknown session %s at %s; ignoring late egomotion",
                        "submit_route for unknown session %s; ignoring late route update",
                    ]
                ),
                "src/driver/src/alpasim_driver/models/__init__.py": "_LAZY_IMPORTS = {}\ndef __getattr__(name: str) -> Any:\n    pass\n",
            }
            for relative, content in files.items():
                path = alpasim_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            patch_file = ROOT / "src" / "alpabridge" / "alpasim_overrides" / "local_checkout.patch"
            self.assertTrue(_patch_effectively_present(alpasim_root, patch_file))

    def test_apply_patch_skips_when_checkout_already_satisfies_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alpasim_root = Path(tmp) / "alpasim"
            files = {
                "src/driver/src/alpasim_driver/main.py": "\n".join(
                    [
                        "current_route: Route | None = None",
                        "def route_waypoints_for_prediction(self) -> list[Vec3] | None:",
                        "route_waypoints=job.session.route_waypoints_for_prediction(),",
                        "prediction_input.runtime_random_seed = job.session.seed",
                    ]
                ),
                "src/driver/src/alpasim_driver/models/base.py": "route_waypoints: list[Any] | None = None\n",
            }
            for relative, content in files.items():
                path = alpasim_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            patch_file = ROOT / "src" / "alpabridge" / "alpasim_overrides" / "route_waypoints.patch"
            with patch("subprocess.run") as run_subprocess, patch(
                "alpabridge.cli.commands.setup_alpasim_local_plugin._run"
            ) as run_apply:
                _apply_alpasim_patch(alpasim_root, patch_file)

            run_subprocess.assert_not_called()
            run_apply.assert_not_called()

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

            with patch("alpabridge.cli.commands.setup_alpasim_local_plugin._run", side_effect=fake_run):
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

            with patch("alpabridge.cli.commands.setup_alpasim_local_plugin._run", side_effect=fake_run):
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
            wizard_driver="token_dagger_bc",
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
            wizard_driver="token_dagger_bc",
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
        with patch.dict(os.environ, {"ALPABRIDGE_ALPASIM_DEPLOY_TARGET": "custom_profile"}, clear=False):
            with patch("platform.machine", return_value="x86_64"):
                self.assertEqual("custom_profile", _wizard_deploy_target())

    def test_platform_preflight_rejects_arm_without_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            with patch("platform.machine", return_value="aarch64"):
                with self.assertRaises(SystemExit) as ctx:
                    _preflight_platform_compatibility()
        self.assertIn("amd64-only", str(ctx.exception))

    def test_platform_preflight_allows_arm_with_override(self) -> None:
        with patch.dict(os.environ, {"ALPABRIDGE_ALLOW_UNSUPPORTED_ALPASIM_ARM": "1"}, clear=False):
            with patch("platform.machine", return_value="aarch64"):
                _preflight_platform_compatibility()

    def test_repo_tracked_scene_preset_is_loadable(self) -> None:
        scene_ids = _scene_ids("fresh_3scene", [])
        self.assertEqual(3, len(scene_ids))

    def test_front_camera_30scene_merged_contains_30_scene_ids(self) -> None:
        scene_ids = _scene_ids("front_camera_30scene_merged", [])
        self.assertEqual(30, len(scene_ids))
        self.assertEqual(30, len(set(scene_ids)))
