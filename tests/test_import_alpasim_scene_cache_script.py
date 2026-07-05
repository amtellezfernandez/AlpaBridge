from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_alpasim_scene_cache.sh"


class ImportAlpaSimSceneCacheScriptTests(unittest.TestCase):
    def test_script_hardlinks_usdz_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "source"
            target_root = Path(tmp) / "target"
            source_usdzs = source_root / "data" / "nre-artifacts" / "all-usdzs"
            source_scenes = source_root / "data" / "scenes"
            source_usdzs.mkdir(parents=True)
            source_scenes.mkdir(parents=True)

            source_file = source_usdzs / "artifact-a.usdz"
            source_file.write_bytes(b"usdz-a")
            (source_usdzs / "artifact-b.usdz").write_bytes(b"usdz-b")
            (source_scenes / "sim_scenes.csv").write_text("scene_id,uuid\nscene-a,artifact-a\n", encoding="utf-8")

            subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--source-root",
                    str(source_root),
                    "--alpasim-root",
                    str(target_root),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            target_file = target_root / "data" / "nre-artifacts" / "all-usdzs" / "artifact-a.usdz"
            self.assertTrue(target_file.is_file())
            self.assertTrue((target_root / "data" / "scenes" / "sim_scenes.csv").is_file())
            self.assertEqual(os.stat(source_file).st_ino, os.stat(target_file).st_ino)

    def test_script_can_copy_instead_of_hardlinking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "source"
            target_root = Path(tmp) / "target"
            source_usdzs = source_root / "data" / "nre-artifacts" / "all-usdzs"
            source_usdzs.mkdir(parents=True)

            source_file = source_usdzs / "artifact-a.usdz"
            source_file.write_bytes(b"usdz-a")

            subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--source-root",
                    str(source_root),
                    "--alpasim-root",
                    str(target_root),
                    "--copy",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            target_file = target_root / "data" / "nre-artifacts" / "all-usdzs" / "artifact-a.usdz"
            self.assertTrue(target_file.is_file())
            self.assertNotEqual(os.stat(source_file).st_ino, os.stat(target_file).st_ino)


if __name__ == "__main__":
    unittest.main()
