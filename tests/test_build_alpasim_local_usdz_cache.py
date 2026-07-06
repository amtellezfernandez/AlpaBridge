from __future__ import annotations

import csv
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


def _write_usdz(path: Path, *, scene_id: str, uuid: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "metadata.yaml",
            yaml.safe_dump(
                {
                    "scene_id": scene_id,
                    "uuid": uuid,
                    "version_string": "26.2-test",
                }
            ),
        )
