from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = ROOT / "scripts" / "prepare_alpasim_public_video_fixture.py"
PACKAGE_SCRIPT = ROOT / "scripts" / "package_alpasim_navsim_reactive_evidence.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AlpaSimNavsimReactiveEvidenceTests(unittest.TestCase):
    def test_fixture_derivation_adds_only_declared_surface_files(self) -> None:
        module = _load_module(PREPARE_SCRIPT, "prepare_alpasim_public_video_fixture")
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "fixture.usdz"
            with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("recorded.txt", b"unchanged")

            module.append_declared_surface(archive_path)

            with ZipFile(archive_path) as archive:
                self.assertEqual(
                    [
                        "recorded.txt",
                        "mesh.ply",
                        "mesh_ground.ply",
                        "WOD2SIM_DERIVATION.json",
                    ],
                    archive.namelist(),
                )
                self.assertEqual(b"unchanged", archive.read("recorded.txt"))
                self.assertEqual(module.FLAT_MESH, archive.read("mesh.ply"))
                self.assertEqual(module.FLAT_MESH, archive.read("mesh_ground.ply"))
                self.assertIn(
                    b"Synthetic flat physics surface",
                    archive.read("WOD2SIM_DERIVATION.json"),
                )
                self.assertEqual(
                    module.ARCHIVE_TIMESTAMP,
                    archive.getinfo("mesh.ply").date_time,
                )

    def test_fixture_preparation_rejects_unpinned_source(self) -> None:
        module = _load_module(PREPARE_SCRIPT, "prepare_alpasim_public_video_fixture_bad")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.usdz"
            source.write_bytes(b"not the pinned fixture")

            with self.assertRaisesRegex(ValueError, "source SHA-256 mismatch"):
                module.prepare_fixture(source, root / "derived.usdz")

    def test_runtime_and_negative_control_log_parsers_are_exact(self) -> None:
        module = _load_module(PACKAGE_SCRIPT, "package_alpasim_navsim_reactive_evidence")
        runtime = (
            "Session COMPLETED: simulated 19.93 sim seconds in 16.51 wall clock "
            "seconds for 1.21x real time (total rollout 18.90s incl. setup/warmup)"
        )
        diagnostic = (
            'details = "RouteFollowingAlpaSimModel detected a frozen camera stream: '
            'pose changed while bytes did not."'
        )

        self.assertEqual(
            {
                "active_wall_clock_s": 16.51,
                "realtime_factor": 1.21,
                "simulated_s": 19.93,
                "total_wall_clock_s": 18.90,
            },
            module.parse_runtime_durations(runtime),
        )
        self.assertEqual(
            "RouteFollowingAlpaSimModel detected a frozen camera stream: "
            "pose changed while bytes did not.",
            module.parse_negative_control_diagnostic(diagnostic),
        )

    def test_linear_percentile_matches_packaged_latency_definition(self) -> None:
        module = _load_module(PACKAGE_SCRIPT, "package_alpasim_navsim_reactive_percentile")

        self.assertEqual(2.5, module.percentile([1.0, 2.0, 3.0, 4.0], 50.0))
        self.assertAlmostEqual(3.85, module.percentile([1.0, 2.0, 3.0, 4.0], 95.0))


if __name__ == "__main__":
    unittest.main()
