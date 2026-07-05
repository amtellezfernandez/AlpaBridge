from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wod2sim.simulator.alpasim_spotlight import DriveCommand, SpotlightReflexAlpaSimModel


class AlpaSimSpotlightLegalityTests(unittest.TestCase):
    def test_adapter_vetoes_illegal_lateral_bypass(self) -> None:
        model = SpotlightReflexAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[object()],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 18.0, "y": 0.0, "z": 0.0},
                {"x": 40.0, "y": 0.0, "z": 0.0},
            ],
            structured_hazards=[
                {"x": 10.0, "y": 0.0, "radius": 1.0, "kind": "vehicle", "label": "center_vehicle"},
            ],
        )

        output = model.predict(prediction_input)
        reasoning = json.loads(output.reasoning_text)

        self.assertTrue(reasoning["transfer_legality_gate_applied"])
        self.assertEqual("nudge_left", reasoning["transfer_legality_previous_maneuver"])
        self.assertIn(reasoning["selected_maneuver"], {"stop", "crawl", "maintain", "slow_yield", "lane_recover"})
        self.assertTrue(
            any(veto["reason"] == "forbidden_lateral_maneuver" for veto in reasoning["transfer_legality_vetoed_tokens"])
        )


if __name__ == "__main__":
    unittest.main()
