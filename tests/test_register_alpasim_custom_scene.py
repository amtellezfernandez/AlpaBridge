from __future__ import annotations

import csv
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

from alpabridge.cli.commands.register_alpasim_custom_scene import main


def _write_usdz(path: Path, *, scene_id: str, uuid: str, version_string: str = "custom-1.0") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "metadata.yaml",
            yaml.safe_dump({"scene_id": scene_id, "uuid": uuid, "version_string": version_string}),
        )


def _read_rows(catalog_path: Path) -> list[dict[str, str]]:
    with catalog_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class RegisterAlpaSimCustomSceneTests(unittest.TestCase):
    def test_appends_a_row_to_a_fresh_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a")

            with patch.object(
                sys,
                "argv",
                [
                    "alpabridge-register-custom-scene",
                    "--usdz",
                    str(usdz),
                    "--catalog-csv",
                    str(catalog),
                ],
            ):
                returncode = main()

            rows = _read_rows(catalog)

        self.assertEqual(0, returncode)
        self.assertEqual(1, len(rows))
        self.assertEqual("scene-a", rows[0]["scene_id"])
        self.assertEqual("uuid-a", rows[0]["uuid"])
        self.assertEqual("local", rows[0]["artifact_repository"])
        self.assertEqual("custom-1.0", rows[0]["nre_version_string"])

    def test_refuses_to_overwrite_existing_scene_id_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a")

            with patch.object(
                sys,
                "argv",
                ["alpabridge-register-custom-scene", "--usdz", str(usdz), "--catalog-csv", str(catalog)],
            ):
                main()

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "alpabridge-register-custom-scene",
                        "--usdz",
                        str(usdz),
                        "--catalog-csv",
                        str(catalog),
                    ],
                ),
                self.assertRaises(SystemExit),
            ):
                main()

    def test_force_updates_a_row_without_dropping_its_other_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a-updated", version_string="v2")
            catalog.write_text(
                "scene_id,uuid,path,artifact_repository,nre_version_string,project_note\n"
                "scene-a,uuid-a,some/custom/path.usdz,local,v1,do not delete me\n",
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "alpabridge-register-custom-scene",
                    "--usdz",
                    str(usdz),
                    "--catalog-csv",
                    str(catalog),
                    "--force",
                ],
            ):
                returncode = main()

            rows = _read_rows(catalog)

        self.assertEqual(0, returncode)
        self.assertEqual(1, len(rows))
        self.assertEqual("uuid-a-updated", rows[0]["uuid"])
        self.assertEqual("v2", rows[0]["nre_version_string"])
        # The fields this command doesn't manage must survive --force untouched.
        self.assertEqual("some/custom/path.usdz", rows[0]["path"])
        self.assertEqual("do not delete me", rows[0]["project_note"])

    def test_preserves_other_rows_and_existing_columns_when_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-b", uuid="uuid-b")
            catalog.write_text(
                "scene_id,uuid,path,artifact_repository,hf_revision,nre_version_string\n"
                "scene-a,uuid-a,some/path.usdz,huggingface,26.02,26.2\n",
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                ["alpabridge-register-custom-scene", "--usdz", str(usdz), "--catalog-csv", str(catalog)],
            ):
                returncode = main()

            rows = _read_rows(catalog)

        self.assertEqual(0, returncode)
        self.assertEqual(2, len(rows))
        self.assertEqual("scene-a", rows[0]["scene_id"])
        self.assertEqual("huggingface", rows[0]["artifact_repository"])
        self.assertEqual("some/path.usdz", rows[0]["path"])
        self.assertEqual("scene-b", rows[1]["scene_id"])
        self.assertEqual("local", rows[1]["artifact_repository"])

    def test_dry_run_does_not_write_the_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a")

            with patch.object(
                sys,
                "argv",
                [
                    "alpabridge-register-custom-scene",
                    "--usdz",
                    str(usdz),
                    "--catalog-csv",
                    str(catalog),
                    "--dry-run",
                ],
            ):
                returncode = main()

        self.assertEqual(0, returncode)
        self.assertFalse(catalog.exists())

    def test_rejects_huggingface_as_artifact_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "alpabridge-register-custom-scene",
                        "--usdz",
                        str(usdz),
                        "--catalog-csv",
                        str(catalog),
                        "--artifact-repository",
                        "huggingface",
                    ],
                ),
                self.assertRaisesRegex(SystemExit, "huggingface"),
            ):
                main()

    def test_rejects_scene_preset_and_catalog_csv_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a")

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "alpabridge-register-custom-scene",
                        "--usdz",
                        str(usdz),
                        "--catalog-csv",
                        str(catalog),
                        "--scene-preset",
                        "fresh_3scene",
                    ],
                ),
                self.assertRaises(SystemExit),
            ):
                main()

    def test_rejects_usdz_missing_required_metadata_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usdz = root / "my-scene.usdz"
            catalog = root / "sim_scenes.csv"
            with zipfile.ZipFile(usdz, "w") as archive:
                archive.writestr("metadata.yaml", yaml.safe_dump({"scene_id": "scene-a"}))

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "alpabridge-register-custom-scene",
                        "--usdz",
                        str(usdz),
                        "--catalog-csv",
                        str(catalog),
                    ],
                ),
                self.assertRaisesRegex(SystemExit, "uuid"),
            ):
                main()

    def test_real_preflight_check_accepts_the_registered_scene(self) -> None:
        """End-to-end: the row this command writes must satisfy the actual,
        unmodified preflight gate alpabridge-ready/-launch use - not a
        reimplementation of it."""
        from alpabridge.cli.commands.run_alpasim_local_external import _preflight_scene_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alpasim_root = root / "alpasim"
            usdz = root / "my-scene.usdz"
            catalog = alpasim_root / "data" / "scenes" / "sim_scenes.csv"
            _write_usdz(usdz, scene_id="scene-a", uuid="uuid-a")

            with patch.object(
                sys,
                "argv",
                ["alpabridge-register-custom-scene", "--usdz", str(usdz), "--catalog-csv", str(catalog)],
            ):
                main()

            # Raises SystemExit on failure; reaching the end of this block is the assertion.
            _preflight_scene_artifacts(alpasim_root=alpasim_root, scene_ids=["scene-a"])
