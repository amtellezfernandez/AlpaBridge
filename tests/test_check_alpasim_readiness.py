from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from wod2sim.cli.commands import check_alpasim_readiness


class CheckAlpaSimReadinessTests(unittest.TestCase):
    def test_readiness_script_calls_all_preflights(self) -> None:
        with patch.object(check_alpasim_readiness, "_resolve_alpasim_root", return_value=Path("/tmp/alpasim")), patch.object(
            check_alpasim_readiness, "_scene_ids", return_value=["scene-1", "scene-2"]
        ), patch.object(
            check_alpasim_readiness,
            "_scene_catalog_paths",
            return_value=[Path("/tmp/alpasim/data/scenes/sim_scenes.csv")],
        ), patch.object(check_alpasim_readiness, "_validate_alpasim_checkout") as validate, patch.object(
            check_alpasim_readiness, "_preflight_alpasim_local_environment"
        ) as local_env, patch.object(
            check_alpasim_readiness, "_preflight_docker_access"
        ) as docker, patch.object(
            check_alpasim_readiness, "_preflight_platform_compatibility"
        ) as platform_check, patch.object(
            check_alpasim_readiness, "_preflight_nvidia_container_runtime"
        ) as gpu_runtime, patch.object(
            check_alpasim_readiness, "_preflight_alpasim_base_image"
        ) as image, patch.object(
            check_alpasim_readiness, "_preflight_scene_artifacts"
        ) as artifacts, patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ) as stdout, patch(
            "sys.argv",
            ["check_alpasim_readiness.py"],
        ):
            check_alpasim_readiness.main()

        validate.assert_called_once_with(Path("/tmp/alpasim"))
        local_env.assert_called_once_with(Path("/tmp/alpasim"))
        docker.assert_called_once_with()
        platform_check.assert_called_once_with()
        gpu_runtime.assert_called_once_with()
        image.assert_called_once_with()
        artifacts.assert_called_once_with(
            alpasim_root=Path("/tmp/alpasim"),
            scene_ids=["scene-1", "scene-2"],
            scene_catalog_paths=[Path("/tmp/alpasim/data/scenes/sim_scenes.csv")],
            local_usdz_dir=None,
        )
        self.assertIn("AlpaSim readiness: OK", stdout.getvalue())
        self.assertIn("scene catalogs: /tmp/alpasim/data/scenes/sim_scenes.csv", stdout.getvalue())
        self.assertIn("local USDZ dir: default", stdout.getvalue())

    def test_readiness_script_can_skip_optional_checks(self) -> None:
        with patch.object(check_alpasim_readiness, "_resolve_alpasim_root", return_value=Path("/tmp/alpasim")), patch.object(
            check_alpasim_readiness, "_scene_ids", return_value=["scene-1"]
        ), patch.object(
            check_alpasim_readiness,
            "_scene_catalog_paths",
            return_value=[Path("/tmp/alpasim/data/scenes/sim_scenes.csv")],
        ), patch.object(check_alpasim_readiness, "_validate_alpasim_checkout"), patch.object(
            check_alpasim_readiness, "_preflight_alpasim_local_environment"
        ) as local_env, patch.object(
            check_alpasim_readiness, "_preflight_docker_access"
        ), patch.object(
            check_alpasim_readiness, "_preflight_platform_compatibility"
        ), patch.object(
            check_alpasim_readiness, "_preflight_nvidia_container_runtime"
        ), patch.object(
            check_alpasim_readiness, "_preflight_alpasim_base_image"
        ) as image, patch.object(
            check_alpasim_readiness, "_preflight_scene_artifacts"
        ) as artifacts, patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ) as stdout, patch(
            "sys.argv",
            ["check_alpasim_readiness.py", "--skip-image", "--skip-local-env", "--skip-scene-artifacts"],
        ):
            check_alpasim_readiness.main()

        local_env.assert_not_called()
        image.assert_not_called()
        artifacts.assert_not_called()
        output = stdout.getvalue()
        self.assertIn("gpu runtime: accessible", output)
        self.assertIn("image: skipped", output)
        self.assertIn("local AlpaSim env: skipped", output)
        self.assertIn("scene artifacts: skipped", output)

    def test_readiness_script_accepts_explicit_local_usdz_dir(self) -> None:
        with patch.object(
            check_alpasim_readiness, "_resolve_alpasim_root", return_value=Path("/tmp/alpasim")
        ), patch.object(
            check_alpasim_readiness, "_scene_ids", return_value=["scene-1"]
        ), patch.object(
            check_alpasim_readiness,
            "_scene_catalog_paths",
            return_value=[Path("/tmp/alpasim/data/scenes/sim_scenes.csv")],
        ), patch.object(
            check_alpasim_readiness, "_validate_alpasim_checkout"
        ), patch.object(
            check_alpasim_readiness, "_preflight_alpasim_local_environment"
        ), patch.object(
            check_alpasim_readiness, "_preflight_docker_access"
        ), patch.object(
            check_alpasim_readiness, "_preflight_platform_compatibility"
        ), patch.object(
            check_alpasim_readiness, "_preflight_nvidia_container_runtime"
        ), patch.object(
            check_alpasim_readiness, "_preflight_alpasim_base_image"
        ), patch.object(
            check_alpasim_readiness, "_preflight_scene_artifacts"
        ) as artifacts, patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ) as stdout, patch(
            "sys.argv",
            [
                "check_alpasim_readiness.py",
                "--local-usdz-dir",
                "data/nre-artifacts/local-usdzs",
            ],
        ):
            check_alpasim_readiness.main()

        artifacts.assert_called_once_with(
            alpasim_root=Path("/tmp/alpasim"),
            scene_ids=["scene-1"],
            scene_catalog_paths=[Path("/tmp/alpasim/data/scenes/sim_scenes.csv")],
            local_usdz_dir=Path("/tmp/alpasim/data/nre-artifacts/local-usdzs"),
        )
        self.assertIn("/tmp/alpasim/data/nre-artifacts/local-usdzs", stdout.getvalue())
