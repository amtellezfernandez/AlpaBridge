from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

from wod2sim.cli.commands.build_alpasim_local_usdz_cache import (
    _existing_by_scene,
    _link_or_copy,
    _selected_catalog_rows,
    validate_local_usdz_cache,
)


class BuildAlpaSimLocalUsdzCacheTests(unittest.TestCase):
    def test_selected_catalog_rows_filters_to_available_paths_in_scene_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "sim_scenes_2602.csv"
            with catalog.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "uuid",
                        "scene_id",
                        "nre_version_string",
                        "path",
                        "last_modified",
                        "artifact_repository",
                        "hf_revision",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "uuid": "uuid-a",
                        "scene_id": "scene-a",
                        "nre_version_string": "26.2",
                        "path": "available.usdz",
                        "last_modified": "now",
                        "artifact_repository": "huggingface",
                        "hf_revision": "26.02",
                    }
                )
                writer.writerow(
                    {
                        "uuid": "uuid-b",
                        "scene_id": "scene-b",
                        "nre_version_string": "26.2",
                        "path": "missing.usdz",
                        "last_modified": "now",
                        "artifact_repository": "huggingface",
                        "hf_revision": "26.02",
                    }
                )

            rows = _selected_catalog_rows(
                catalog_paths=[catalog],
                scene_ids=["scene-b", "scene-a"],
                available_paths={"available.usdz"},
            )

        self.assertEqual(["scene-a"], [row["scene_id"] for row in rows])

    def test_existing_by_scene_reads_usdz_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            _write_usdz(cache_dir / "uuid-a.usdz", scene_id="scene-a", uuid="uuid-a")

            existing = _existing_by_scene(cache_dir)

        self.assertEqual("uuid-a", existing["scene-a"]["uuid"])
        self.assertEqual("26.2-test", existing["scene-a"]["version_string"])

    def test_link_or_copy_falls_back_when_hardlink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.usdz"
            target = Path(tmp) / "target.usdz"
            source.write_text("stub", encoding="utf-8")

            with patch("wod2sim.cli.commands.build_alpasim_local_usdz_cache.os.link", side_effect=OSError):
                status = _link_or_copy(source, target)

            self.assertEqual("copy", status)
            self.assertEqual("stub", target.read_text(encoding="utf-8"))

    def test_validate_local_usdz_cache_accepts_complete_metadata_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            _write_usdz(cache_dir / "uuid-a.usdz", scene_id="scene-a", uuid="uuid-a")
            _write_usdz(cache_dir / "uuid-b.usdz", scene_id="scene-b", uuid="uuid-b")

            report = validate_local_usdz_cache(
                scene_preset="front_camera_50scene_public2602",
                scene_ids=["scene-a", "scene-b"],
                local_usdz_dir=cache_dir,
                hf_revision="26.02",
            )

        self.assertTrue(report["valid"])
        self.assertEqual(2, report["present_scene_count"])
        self.assertEqual([], report["missing_scene_ids"])
        self.assertEqual([], report["invalid_revision_scene_ids"])

    def test_validate_local_usdz_cache_reports_missing_and_revision_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            _write_usdz(
                cache_dir / "uuid-a.usdz",
                scene_id="scene-a",
                uuid="uuid-a",
                version_string="25.01",
            )

            report = validate_local_usdz_cache(
                scene_preset="front_camera_50scene_public2602",
                scene_ids=["scene-a", "scene-b"],
                local_usdz_dir=cache_dir,
                hf_revision="26.02",
            )

        self.assertFalse(report["valid"])
        self.assertEqual(["scene-b"], report["missing_scene_ids"])
        self.assertEqual(["scene-a"], report["invalid_revision_scene_ids"])

    def test_validate_only_main_is_offline_and_does_not_query_huggingface(self) -> None:
        from wod2sim.cli.commands import build_alpasim_local_usdz_cache as module

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            _write_usdz(cache_dir / "uuid-a.usdz", scene_id="scene-a", uuid="uuid-a")

            with patch.object(module, "_resolve_alpasim_root", return_value=Path("/tmp/alpasim")), patch.object(
                module, "_scene_ids", return_value=["scene-a"]
            ), patch.object(
                module,
                "_hf_available_paths",
                side_effect=AssertionError("validate-only must not query Hugging Face"),
            ), patch.object(
                sys,
                "argv",
                [
                    "wod2sim-build-local-cache",
                    "--scene-preset",
                    "front_camera_50scene_public2602",
                    "--local-usdz-dir",
                    str(cache_dir),
                    "--hf-revision",
                    "26.02",
                    "--validate-only",
                ],
            ), patch(
                "sys.stdout",
                new_callable=io.StringIO,
            ) as stdout:
                returncode = module.main()

            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, returncode)
        self.assertTrue(payload["valid"])
        self.assertEqual("wod2sim_local_usdz_cache_validation_v1", payload["schema"])


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
