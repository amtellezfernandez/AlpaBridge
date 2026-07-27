from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

from alpabridge.audit.alpasim_export import export_alpasim_audit_log
from alpabridge.audit.review import has_intervention
from alpabridge.simulator.alpasim_contract import DriveCommand
from alpabridge.simulator.mpc_planner import MPCPlannerAlpaSimModel


class MpcPlannerAuditExportTests(unittest.TestCase):
    def test_mpc_planner_runs_produce_a_real_non_empty_audit_export(self) -> None:
        # Regression test: alpasim_export.py used to have no reader for
        # driver/mpc-planner-log.jsonl at all (it was wired into
        # audit_run.py's DRIVER_LOG_SPECS but missed here), so
        # alpabridge-audit-run on an mpc_planner run silently produced
        # frame_count: 0 - no error, just an empty audit trail.
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            log_path = run_dir / "driver" / "mpc-planner-log.jsonl"
            model = MPCPlannerAlpaSimModel(
                camera_ids=["front"], context_length=1, output_frequency_hz=4, log_path=log_path
            )
            prediction_input = SimpleNamespace(
                camera_images={
                    "front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8), timestamp_us=1000)]
                },
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[object()],
                route_waypoints=[{"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 40.0, "y": 0.0, "z": 0.0}],
                alpasignal={"hazards": []},
            )
            model.predict(prediction_input)

            output_dir = Path(tmp) / "evidence"
            manifest = export_alpasim_audit_log(run_dir, output_dir)
            frames = [
                json.loads(line) for line in (output_dir / "frames.jsonl").read_text().splitlines()
            ]

        self.assertEqual(1, manifest["frame_count"])
        self.assertEqual(1, len(frames))
        self.assertEqual("mpc_planner", frames[0]["step"]["action_mode"])
        self.assertEqual([0.0, 0.0], frames[0]["route"]["start"])
        self.assertEqual([40.0, 0.0], frames[0]["route"]["goal"])
        # The false-positive-intervention bug this session fixed must not
        # resurface for the newly-added reader either.
        self.assertFalse(has_intervention(frames[0]))


if __name__ == "__main__":
    unittest.main()
