from __future__ import annotations

import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest

import numpy as np

try:
    import torch
except ImportError:  # pragma: no cover - exercised in dependency-light artifact checks.
    torch = None

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests.pyproject_helpers import load_string_tables

from wod2sim.audit.alpasim_export import export_alpasim_audit_log
from wod2sim.neutral.alpasim_metrics import build_alpasim_evidence, load_alpasim_metrics
from wod2sim.simulator.alpasim_direct_actor_planner import (
    DirectActorPlannerAlpaSimModel,
    DirectPlannerConfig,
    plan_direct_actor_trajectory,
)
from wod2sim.simulator.alpasim_signal import extract_alpasim_signal, scenario_from_command
from wod2sim.simulator.alpasim_spotlight import DriveCommand, SpotlightReflexAlpaSimModel
from wod2sim.simulator.alpasim_token_bc import (
    TOKEN_ORDER,
    TokenBCAlpaSimModel,
    _GeomMLP,
    _actor_axis_route_guard_required,
    _actor_route_stable_violation,
    _adapter_spotlight_config,
    _candidate_axis_signals,
    _prediction_ego_pose_world,
    _prediction_timestamp_us,
)
from wod2sim.simulator.environment import scenario_at_tick
from wod2sim.simulator.perception import perceive_scene
from wod2sim.simulator.spotlight_reflex import evaluate_maneuver_candidates
from wod2sim.simulator.world_model import update_world_state


class AlpaSimIntegrationTests(unittest.TestCase):
    def test_pyproject_registers_alpasim_plugin_entrypoints(self) -> None:
        pyproject = load_string_tables("pyproject.toml")
        self.assertEqual(
            pyproject['project.entry-points."alpasim.models"']["spotlight_reflex"],
            "wod2sim.simulator.alpasim_spotlight:SpotlightReflexAlpaSimModel",
        )
        self.assertEqual(
            pyproject['project.entry-points."alpasim.models"']["token_dagger_bc"],
            "wod2sim.simulator.alpasim_token_bc:TokenBCAlpaSimModel",
        )
        self.assertEqual(
            pyproject['project.entry-points."alpasim.models"']["direct_actor_planner"],
            "wod2sim.simulator.alpasim_direct_actor_planner:DirectActorPlannerAlpaSimModel",
        )
        self.assertEqual(
            pyproject['project.entry-points."alpasim.configs"']["spotlight_reflex"],
            "wod2sim.simulator.alpasim_configs",
        )
        self.assertEqual(
            pyproject["project.scripts"]["wod2sim-build-oracle-proxy"],
            "wod2sim.cli.commands.build_alpasim_oracle_actor_proxy:main",
        )
        self.assertEqual(
            pyproject["project.scripts"]["wod2sim-audit-run"],
            "wod2sim.cli.commands.audit_run:main",
        )
        self.assertEqual(
            pyproject["project.scripts"]["wod2sim-support-bundle"],
            "wod2sim.cli.commands.support_bundle:main",
        )

    def test_alpasim_driver_config_exists(self) -> None:
        config_path = Path("src/wod2sim/simulator/alpasim_configs/driver/spotlight_reflex.yaml")
        config = config_path.read_text()
        self.assertIn("model_type: spotlight_reflex", config)
        self.assertIn("output_frequency_hz: 4", config)

    def test_direct_actor_planner_config_exists(self) -> None:
        config_path = Path("src/wod2sim/simulator/alpasim_configs/driver/direct_actor_planner.yaml")
        config = config_path.read_text()
        self.assertIn("model_type: direct_actor_planner", config)
        self.assertIn('device: "cpu"', config)
        self.assertIn("trajectory_optimizer:", config)

    def test_alpasim_token_dagger_configs_exist_and_default_to_cuda(self) -> None:
        for name in (
            "token_dagger_bc.yaml",
            "token_dagger_srcdecay.yaml",
            "token_dagger_bc_clamped.yaml",
            "token_dagger_srcdecay_clamped.yaml",
        ):
            config_path = Path("src/wod2sim/simulator/alpasim_configs/driver") / name
            config = config_path.read_text()
            self.assertIn("model_type: token_dagger_bc", config)
            self.assertIn('device: "cuda"', config)
            if name.endswith("_clamped.yaml"):
                self.assertNotIn("trajectory_mode:", config)
                self.assertNotIn("max_lateral_offset_m:", config)

    def test_alpasim_signal_uses_structured_hazards(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[object()],
            alpasignal={
                "hazards": [
                    {
                        "forward_m": 12.0,
                        "lateral_m": -1.5,
                        "radius_m": 1.25,
                        "type": "vehicle",
                        "id": "cutin_0",
                    }
                ]
            },
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(signal["structured_hazards"][0]["label"], "cutin_0")
        self.assertEqual(len(scenario.obstacles), 1)
        self.assertEqual(scenario.obstacles[0].x, 12.0)
        self.assertEqual(scenario.obstacles[0].kind, "vehicle")

    def test_direct_actor_planner_returns_trajectory_without_token_selector(self) -> None:
        model = DirectActorPlannerAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[object()],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 30.0, "y": 0.0, "z": 0.0},
                {"x": 60.0, "y": 0.0, "z": 0.0},
            ],
            alpasignal={"hazards": []},
        )

        output = model.predict(prediction_input)
        reasoning = json.loads(output.reasoning_text)

        self.assertEqual(output.trajectory_xy.shape, (20, 2))
        self.assertEqual(reasoning["planner"], "selector_free_actor_aware_grid")
        self.assertNotIn("selected_maneuver", reasoning)
        self.assertGreater(reasoning["plan"]["progress_m"], 0.0)

    def test_direct_actor_planner_does_not_brake_into_closing_rear_actor(self) -> None:
        scenario = scenario_at_tick(
            scenario_from_command(
                "straight",
                {
                    "route_waypoints": [
                        {"x": 0.0, "y": 0.0, "z": 0.0},
                        {"x": 40.0, "y": 0.0, "z": 0.0},
                        {"x": 80.0, "y": 0.0, "z": 0.0},
                    ],
                    "structured_hazards": [
                        {
                            "x": -8.0,
                            "y": 0.0,
                            "radius": 1.0,
                            "width": 2.0,
                            "length": 4.0,
                            "kind": "vehicle",
                            "label": "rear_closing_vehicle",
                            "vx": 2.0,
                            "vy": 0.0,
                        }
                    ],
                },
            ),
            0,
        )

        plan = plan_direct_actor_trajectory(
            scenario,
            speed_mps=8.0,
            config=DirectPlannerConfig(
                speed_scales=(0.0, 0.35, 0.75, 1.0),
                lateral_offsets_m=(0.0,),
                rear_flow_weight=5000.0,
            ),
        )

        self.assertGreaterEqual(plan.metrics["speed_scale"], 0.75)
        self.assertGreaterEqual(plan.metrics["candidate_mean_speed_mps"], 6.0)
        self.assertEqual(plan.metrics["rear_actor_count"], 1)
        self.assertEqual(plan.metrics["rear_closing_actor_count"], 1)

    def test_direct_actor_planner_max_clearance_objective_ignores_cost_tie_bias(self) -> None:
        scenario = scenario_at_tick(
            scenario_from_command(
                "straight",
                {
                    "route_waypoints": [
                        {"x": 0.0, "y": 0.0, "z": 0.0},
                        {"x": 40.0, "y": 0.0, "z": 0.0},
                    ],
                    "structured_hazards": [
                        {
                            "x": 8.0,
                            "y": 0.0,
                            "radius": 0.8,
                            "kind": "vehicle",
                            "label": "center_obstacle",
                        }
                    ],
                },
            ),
            0,
        )
        base_config = dict(
            speed_scales=(0.8,),
            lateral_offsets_m=(0.0, 3.0),
            max_lateral_offset_m=3.0,
            clearance_weight=0.0,
            collision_weight=0.0,
            lane_weight=0.0,
            route_weight=0.0,
            lateral_weight=10.0,
        )

        cost_plan = plan_direct_actor_trajectory(
            scenario,
            speed_mps=6.0,
            config=DirectPlannerConfig(selection_objective="cost", **base_config),
        )
        clearance_plan = plan_direct_actor_trajectory(
            scenario,
            speed_mps=6.0,
            config=DirectPlannerConfig(selection_objective="max_clearance", **base_config),
        )

        self.assertEqual(cost_plan.metrics["selection_objective"], "cost")
        self.assertEqual(clearance_plan.metrics["selection_objective"], "max_clearance")
        self.assertLess(cost_plan.metrics["min_clearance_m"], clearance_plan.metrics["min_clearance_m"])
        self.assertAlmostEqual(clearance_plan.metrics["lateral_offset_m"], 3.0)

    def test_alpasim_signal_uses_route_waypoints_as_lane_center(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[object()],
            route_waypoints=[
                SimpleNamespace(x=0.0, y=0.0, z=0.0),
                SimpleNamespace(x=18.0, y=2.0, z=0.0),
                SimpleNamespace(x=40.0, y=8.0, z=0.0),
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(3, signal["route_waypoint_count"])
        self.assertEqual("alpasim_waypoints", scenario.tags["route_source"])
        self.assertEqual("3", scenario.tags["route_waypoint_count"])
        self.assertAlmostEqual(40.0, scenario.goal[0])
        self.assertAlmostEqual(8.0, scenario.goal[1])
        self.assertLess(scenario.lane_half_width, 6.0)

    def test_alpasim_signal_preserves_static_hazard_shape_metadata(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[object()],
            structured_hazards=[
                {
                    "x": 10.0,
                    "y": 1.5,
                    "radius": 0.8,
                    "length_m": 5.2,
                    "heading_rad": 1.57,
                    "kind": "vehicle",
                    "label": "parked_van",
                }
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(len(scenario.obstacles), 1)
        obstacle = scenario.obstacles[0]
        self.assertAlmostEqual(obstacle.length or 0.0, 5.2)
        self.assertAlmostEqual(obstacle.heading, 1.57, places=2)

    def test_alpasim_signal_adds_caution_zone_for_low_visibility_braking(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.zeros((4, 4, 3), dtype=np.uint8))]},
            speed=0.2,
            acceleration=-3.0,
            ego_pose_history=[],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertGreaterEqual(signal["visibility_risk"], 0.5)
        self.assertGreaterEqual(signal["dynamics_risk"], 0.5)
        self.assertEqual(scenario.obstacles[0].label, "alpasim_signal_caution")

    def test_alpasim_signal_preserves_moving_hazards_as_actors(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[],
            traffic_hazards=[
                {
                    "x": 14.0,
                    "y": 2.0,
                    "radius": 1.0,
                    "kind": "pedestrian",
                    "label": "crossing_0",
                    "vx": 0.0,
                    "vy": -2.0,
                }
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(len(scenario.obstacles), 0)
        self.assertEqual(len(scenario.actors), 1)
        self.assertEqual(scenario.actors[0].role, "crossing_0")
        self.assertEqual(scenario.actors[0].vy, -2.0)

    def test_alpasim_signal_preserves_moving_hazard_shape_metadata(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[],
            traffic_hazards=[
                {
                    "x": 14.0,
                    "y": 2.0,
                    "radius": 0.9,
                    "width_m": 2.2,
                    "length_m": 4.8,
                    "heading_rad": 1.2,
                    "kind": "vehicle",
                    "label": "crossing_vehicle",
                    "vx": 0.0,
                    "vy": -2.0,
                }
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(len(scenario.actors), 1)
        actor = scenario.actors[0]
        self.assertAlmostEqual(actor.width, 2.2)
        self.assertAlmostEqual(actor.length, 4.8)
        self.assertEqual(actor.role, "crossing_vehicle")

    def test_alpasim_signal_preserves_explicit_moving_behavior(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[],
            traffic_hazards=[
                {
                    "x": 14.0,
                    "y": 2.0,
                    "radius": 1.0,
                    "kind": "vehicle",
                    "label": "lead_vehicle",
                    "vx": 0.0,
                    "vy": -2.0,
                    "behavior": "sudden_brake",
                }
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(scenario.actors[0].behavior, "sudden_brake")

    def test_alpasim_signal_infers_supported_behavior_from_label(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[],
            traffic_hazards=[
                {
                    "x": 14.0,
                    "y": 2.0,
                    "radius": 1.0,
                    "kind": "vehicle",
                    "label": "wrong_way_vehicle",
                    "vx": -3.0,
                    "vy": 0.0,
                },
                {
                    "x": 8.0,
                    "y": 3.0,
                    "radius": 0.6,
                    "kind": "pedestrian",
                    "label": "erratic_pedestrian",
                    "vx": 0.0,
                    "vy": -1.5,
                },
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)
        behaviors = {actor.role: actor.behavior for actor in scenario.actors}

        self.assertEqual(behaviors["wrong_way_vehicle"], "wrong_way")
        self.assertEqual(behaviors["erratic_pedestrian"], "erratic_pedestrian")

    def test_alpasim_signal_infers_sudden_brake_from_acceleration(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[],
            traffic_hazards=[
                {
                    "x": 14.0,
                    "y": 0.0,
                    "radius": 1.0,
                    "kind": "vehicle",
                    "label": "lead_vehicle",
                    "vx": 2.0,
                    "vy": 0.0,
                    "acceleration_mps2": -3.5,
                }
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertEqual(scenario.actors[0].behavior, "sudden_brake")

    def test_alpasim_signal_preserves_explicit_heading_for_elongated_vehicle(self) -> None:
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            speed=8.0,
            acceleration=0.0,
            ego_pose_history=[],
            traffic_hazards=[
                {
                    "x": 14.0,
                    "y": 2.0,
                    "radius": 0.9,
                    "width_m": 2.0,
                    "length_m": 5.5,
                    "heading_rad": 1.2,
                    "kind": "vehicle",
                    "label": "cut_in_vehicle",
                    "vx": 2.0,
                    "vy": 0.0,
                }
            ],
        )

        signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command("straight", signal)

        self.assertAlmostEqual(scenario.actors[0].heading, 1.2, places=6)

    def test_alpasim_adapter_reasoning_exposes_world_state_summary(self) -> None:
        model = SpotlightReflexAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[],
            structured_hazards=[
                {
                    "x": 8.0,
                    "y": 1.0,
                    "radius": 0.9,
                    "length_m": 4.5,
                    "heading_rad": 0.0,
                    "kind": "vehicle",
                    "label": "lead_vehicle",
                }
            ],
        )

        prediction = model.predict(prediction_input)
        reasoning = prediction.reasoning_text

        self.assertIsNotNone(reasoning)
        assert reasoning is not None
        self.assertIn('"route_blockage"', reasoning)
        self.assertIn('"preferred_escape_side"', reasoning)
        self.assertIn('"obstacle_pressure"', reasoning)

    def test_token_bc_alpasim_adapter_loads_checkpoint_and_predicts(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )

            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
            )
            prediction = adapter.predict(prediction_input)

        self.assertEqual((20, 2), prediction.trajectory_xy.shape)
        self.assertEqual((20,), prediction.headings.shape)
        self.assertIsNotNone(prediction.reasoning_text)
        assert prediction.reasoning_text is not None
        self.assertIn('"selected_maneuver": "maintain"', prediction.reasoning_text)

    def test_token_bc_alpasim_adapter_can_clamp_lateral_token_geometry(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("evasive_left")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=10.0,
                acceleration=0.0,
                ego_pose_history=[],
            )
            raw_adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                trajectory_mode="token",
            )
            clamped_adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                trajectory_mode="clamped_lateral",
                max_lateral_offset_m=2.0,
            )

            raw_prediction = raw_adapter.predict(prediction_input)
            clamped_prediction = clamped_adapter.predict(prediction_input)

        self.assertGreater(float(raw_prediction.trajectory_xy[:, 1].max()), 6.0)
        self.assertLessEqual(float(clamped_prediction.trajectory_xy[:, 1].max()), 2.05)
        self.assertIn('"trajectory_mode": "clamped_lateral"', clamped_prediction.reasoning_text or "")

    def test_token_bc_alpasim_adapter_hybrid_logs_selection_trace(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            selection_log_path = Path(tmp) / "selection-log.jsonl"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("evasive_left")] = 5.0
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 4.95
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )

            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                selection_mode="hybrid_veto",
                hybrid_top_k=2,
                hybrid_geometric_weight=20.0,
                selection_log_path=selection_log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
                scene_id="clipgt-test-scene",
            )

            prediction = adapter.predict(prediction_input)
            reasoning_payload = json.loads(prediction.reasoning_text or "{}")
            trace = reasoning_payload["selection_trace"]
            self.assertEqual("hybrid_veto", reasoning_payload["selection_mode"])
            self.assertEqual("evasive_left", trace["dagger_argmax_token"])
            self.assertEqual("maintain", trace["hybrid_token"])
            self.assertEqual("maintain", trace["spotlight_token"])
            self.assertTrue(selection_log_path.is_file())
            records = [json.loads(line) for line in selection_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(1, len(records))
            self.assertEqual("clipgt-test-scene", records[0]["scene_id"])
            self.assertEqual("evasive_left", records[0]["dagger_argmax_token"])
            self.assertEqual("maintain", records[0]["hybrid_token"])
            self.assertEqual("spotlight_wins", records[0]["decision_type"])

    def test_token_bc_alpasim_adapter_hard_veto_suppresses_bad_argmax(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            selection_log_path = Path(tmp) / "selection-log.jsonl"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("evasive_left")] = 5.0
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 4.95
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )

            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                selection_mode="hybrid_veto",
                hybrid_top_k=2,
                hybrid_geometric_weight=0.0,
                hybrid_veto_margin=0.0,
                hybrid_max_geometric_rank=1,
                selection_log_path=selection_log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
                scene_id="clipgt-hard-veto",
            )

            prediction = adapter.predict(prediction_input)
            trace = json.loads(prediction.reasoning_text or "{}")["selection_trace"]
            records = [
                json.loads(line)
                for line in selection_log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual("evasive_left", trace["dagger_argmax_token"])
        self.assertEqual("maintain", trace["hybrid_token"])
        self.assertTrue(trace["dagger_argmax_vetoed"])
        self.assertFalse(trace["used_fallback_geometric"])
        self.assertIn(trace["veto_reason"], {"geometric_gap", "geometric_rank"})
        self.assertEqual(1, trace["max_geometric_rank"])
        self.assertEqual(0.0, trace["veto_margin"])
        self.assertNotIn("evasive_left", trace["safe_topk_tokens"])
        self.assertIn("maintain", trace["safe_topk_tokens"])
        self.assertTrue(any(row["token"] == "evasive_left" for row in trace["vetoed_tokens"]))
        self.assertEqual(1, len(records))
        self.assertEqual("clipgt-hard-veto", records[0]["scene_id"])
        self.assertTrue(records[0]["dagger_argmax_vetoed"])
        self.assertIn(records[0]["veto_reason"], {"geometric_gap", "geometric_rank"})

    def test_token_bc_alpasim_adapter_hard_veto_logs_geometric_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("evasive_left")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                selection_mode="hybrid_veto",
                hybrid_top_k=1,
                hybrid_veto_margin=0.0,
                hybrid_max_geometric_rank=1,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
            )

            prediction = adapter.predict(prediction_input)
            trace = json.loads(prediction.reasoning_text or "{}")["selection_trace"]

        self.assertEqual("evasive_left", trace["dagger_argmax_token"])
        self.assertEqual("maintain", trace["hybrid_token"])
        self.assertTrue(trace["dagger_argmax_vetoed"])
        self.assertTrue(trace["used_fallback_geometric"])
        self.assertEqual("fallback_geometric", trace["decision_type"])

    def test_token_bc_alpasim_adapter_axis_constrained_preserves_safe_dagger_argmax(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("evasive_left")] = 5.0
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 4.95
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                trajectory_mode="clamped_lateral",
                selection_mode="axis_constrained",
                hybrid_top_k=2,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
            )

            prediction = adapter.predict(prediction_input)
            trace = json.loads(prediction.reasoning_text or "{}")["selection_trace"]

        self.assertEqual("evasive_left", trace["dagger_argmax_token"])
        self.assertEqual("evasive_left", trace["hybrid_token"])
        self.assertFalse(trace["dagger_argmax_vetoed"])
        self.assertEqual("dagger_wins", trace["decision_type"])

    def test_token_bc_alpasim_adapter_axis_lexicographic_prefers_geometry_among_safe_tokens(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            selection_log_path = Path(tmp) / "selection-log.jsonl"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("evasive_left")] = 5.0
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 4.95
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                trajectory_mode="clamped_lateral",
                selection_mode="axis_lexicographic",
                hybrid_top_k=2,
                selection_log_path=selection_log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
                scene_id="clipgt-axis-lexicographic",
            )

            prediction = adapter.predict(prediction_input)
            trace = json.loads(prediction.reasoning_text or "{}")["selection_trace"]

        self.assertEqual("evasive_left", trace["dagger_argmax_token"])
        self.assertEqual("maintain", trace["hybrid_token"])
        self.assertFalse(trace["dagger_argmax_vetoed"])
        self.assertEqual("spotlight_wins", trace["decision_type"])

    def test_token_bc_alpasim_adapter_actor_axis_logs_explicit_axis_signals(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            selection_log_path = Path(tmp) / "selection-log.jsonl"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 5.0
            last_linear.bias.data[TOKEN_ORDER.index("slow_yield")] = 4.99
            last_linear.bias.data[TOKEN_ORDER.index("stop")] = 4.98
            last_linear.bias.data[TOKEN_ORDER.index("crawl")] = 4.97
            last_linear.bias.data[TOKEN_ORDER.index("nudge_left")] = 4.96
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                trajectory_mode="clamped_lateral",
                selection_mode="actor_axis_constrained",
                hybrid_top_k=5,
                selection_log_path=selection_log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
                route_waypoints=[
                    {"x": 0.0, "y": 0.0, "z": 0.0},
                    {"x": 25.0, "y": 0.0, "z": 0.0},
                    {"x": 55.0, "y": 0.0, "z": 0.0},
                ],
                traffic_hazards=[
                    {
                        "x": 8.0,
                        "y": 1.0,
                        "radius": 1.0,
                        "kind": "vehicle",
                        "label": "crossing_vehicle",
                        "vx": -1.0,
                        "vy": 0.0,
                    }
                ],
            )

            prediction = adapter.predict(prediction_input)
            trace = json.loads(prediction.reasoning_text or "{}")["selection_trace"]
            records = [
                json.loads(line)
                for line in selection_log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual("actor_axis_constrained", json.loads(prediction.reasoning_text or "{}")["selection_mode"])
        self.assertEqual("maintain", trace["dagger_argmax_token"])
        self.assertNotEqual("maintain", trace["hybrid_token"])
        self.assertIn(trace["hybrid_token"], {"crawl", "slow_yield", "stop", "lane_recover"})
        self.assertIn(trace["veto_reason"], {"none", "horizon_clearance", "unsafe_action", "actor_route_guard"})
        self.assertIn("axis_signals", trace)
        self.assertIn("maintain", trace["axis_signals"])
        self.assertIn("actor_action_clearance_m", trace["axis_signals"]["maintain"])
        self.assertEqual("time_swept", trace["axis_signals"]["maintain"]["actor_forecast_mode"])
        self.assertIn("lane_margin_m", trace["axis_signals"]["maintain"])
        self.assertEqual("alpasim_waypoints", trace["axis_signals"]["maintain"]["route_source"])
        self.assertIn("route_start_deviation_m", trace["axis_signals"]["maintain"])
        self.assertIn("route_deviation_m", trace["axis_signals"]["maintain"])
        self.assertIn("route_final_deviation_m", trace["axis_signals"]["maintain"])
        self.assertIn("route_recovery_m", trace["axis_signals"]["maintain"])
        self.assertIn("rear_flow_ttc_s", trace["axis_signals"]["maintain"])
        self.assertIn("candidate_mean_forward_speed_mps", trace["axis_signals"]["maintain"])
        self.assertIn("hybrid_axis_scores", trace)
        self.assertIn("route_stable_actor_safe", trace["hybrid_axis_scores"]["maintain"])
        self.assertIn("rear_flow_safe", trace["hybrid_axis_scores"]["maintain"])
        self.assertEqual("time_swept", trace["hybrid_axis_scores"]["maintain"]["actor_forecast_mode"])
        self.assertIn("route_deviation_m", trace["hybrid_axis_scores"]["maintain"])
        self.assertEqual(1, len(records))
        self.assertIn("axis_signals", records[0])
        self.assertIn("actor_route_guard_applied", records[0])

    def test_actor_axis_rear_flow_signal_vetoes_slow_candidate_under_closing_rear_actor(self) -> None:
        signal = extract_alpasim_signal(
            SimpleNamespace(
                camera_images={"front": [SimpleNamespace(image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[],
                route_waypoints=[
                    {"x": 0.0, "y": 0.0, "z": 0.0},
                    {"x": 30.0, "y": 0.0, "z": 0.0},
                    {"x": 60.0, "y": 0.0, "z": 0.0},
                ],
                traffic_hazards=[
                    {
                        "x": -10.5,
                        "y": 0.1,
                        "radius": 1.0,
                        "length": 4.0,
                        "kind": "vehicle",
                        "label": "rear_closing_vehicle",
                        "vx": 0.0,
                        "vy": 0.0,
                    }
                ],
            )
        )
        scenario = scenario_at_tick(scenario_from_command("straight", signal), 0)
        position = scenario.start
        perception = perceive_scene(scenario, position)
        world_state = update_world_state(scenario, position, perception)
        config = _adapter_spotlight_config(
            trajectory_mode="clamped_lateral",
            max_lateral_offset_m=2.0,
            selection_mode="actor_axis_constrained",
        )
        evaluations, _ = evaluate_maneuver_candidates(
            scenario,
            position,
            world_state,
            perception,
            speed_mps=6.0,
            config=config,
        )
        signals = _candidate_axis_signals(
            evaluations,
            scenario=scenario,
            position=position,
            speed_mps=6.0,
            config=config,
        )
        evaluations_by_name = {evaluation.candidate.name: evaluation for evaluation in evaluations}

        self.assertTrue(signals["stop"]["rear_flow_risk"])
        self.assertTrue(signals["crawl"]["rear_flow_risk"])
        self.assertFalse(signals["maintain"]["rear_flow_risk"])
        self.assertEqual(
            "rear_flow_risk",
            _actor_route_stable_violation("stop", evaluations_by_name["stop"], signals["stop"]),
        )
        self.assertEqual(
            "rear_flow_risk",
            _actor_route_stable_violation("crawl", evaluations_by_name["crawl"], signals["crawl"]),
        )
        self.assertIsNone(_actor_route_stable_violation("maintain", evaluations_by_name["maintain"], signals["maintain"]))
        self.assertTrue(_actor_axis_route_guard_required("stop", evaluations_by_name, signals))
        self.assertFalse(_actor_axis_route_guard_required("maintain", evaluations_by_name, signals))

    def test_token_bc_alpasim_adapter_injects_oracle_actor_proxy_by_timestamp(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            checkpoint_path = tmp_path / "token_dagger_bc.pt"
            proxy_path = tmp_path / "oracle_actor_proxy.json"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            proxy_path.write_text(
                json.dumps(
                    {
                        "schema": "alpasim_oracle_actor_proxy_v2",
                        "frames": {
                            "1001000": {
                                "timestamp_us": 1001000,
                                "scene_id": "clipgt-oracle",
                                "world_actors": [
                                    {
                                        "world_x": 12.0,
                                        "world_y": 1.0,
                                        "world_vx": 2.0,
                                        "world_vy": 0.0,
                                        "world_heading": 0.0,
                                        "radius": 1.2,
                                        "width": 2.0,
                                        "length": 4.5,
                                        "kind": "automobile",
                                        "label": "oracle-car",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                oracle_actor_proxy_path=proxy_path,
                oracle_actor_proxy_tolerance_us=20_000,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[
                    SimpleNamespace(
                        timestamp_us=1000000,
                        pose=SimpleNamespace(
                            vec=SimpleNamespace(x=10.0, y=1.0, z=0.0),
                            quat=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
                        ),
                    )
                ],
            )

            prediction = adapter.predict(prediction_input)
            payload = json.loads(prediction.reasoning_text or "{}")
            signal = payload["alpasim_signal"]

        self.assertTrue(signal["oracle_actor_proxy_enabled"])
        self.assertTrue(signal["oracle_actor_proxy_hit"])
        self.assertEqual(1, signal["oracle_actor_proxy_count"])
        self.assertEqual(1, signal["oracle_actor_proxy_world_actor_count"])
        self.assertEqual("world", signal["oracle_actor_proxy_frame_space"])
        self.assertEqual(1_000, signal["oracle_actor_proxy_delta_us"])
        self.assertEqual("oracle-car", signal["structured_hazards"][0]["label"])
        self.assertAlmostEqual(2.0, signal["structured_hazards"][0]["x"], places=5)
        self.assertAlmostEqual(0.0, signal["structured_hazards"][0]["y"], places=5)
        self.assertAlmostEqual(-4.0, signal["structured_hazards"][0]["vx"], places=5)

    def test_token_bc_alpasim_adapter_transforms_oracle_world_actors_into_current_ego_frame(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            checkpoint_path = tmp_path / "token_dagger_bc.pt"
            proxy_path = tmp_path / "oracle_actor_proxy.json"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            proxy_path.write_text(
                json.dumps(
                    {
                        "schema": "alpasim_oracle_actor_proxy_v2",
                        "frames": {
                            "1001000": {
                                "timestamp_us": 1001000,
                                "scene_id": "clipgt-oracle",
                                "world_actors": [
                                    {
                                        "world_x": 12.0,
                                        "world_y": 1.0,
                                        "world_vx": 2.0,
                                        "world_vy": 0.0,
                                        "world_heading": 0.0,
                                        "radius": 1.2,
                                        "width": 2.0,
                                        "length": 4.5,
                                        "kind": "automobile",
                                        "label": "oracle-car",
                                        "source_rel_x": 2.0,
                                        "source_rel_y": 0.0,
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                oracle_actor_proxy_path=proxy_path,
                oracle_actor_proxy_tolerance_us=20_000,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[
                    SimpleNamespace(
                        timestamp_us=1000000,
                        pose=SimpleNamespace(
                            vec=SimpleNamespace(x=11.0, y=1.0, z=0.0),
                            quat=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
                        ),
                    )
                ],
            )

            prediction = adapter.predict(prediction_input)
            signal = json.loads(prediction.reasoning_text or "{}")["alpasim_signal"]

        self.assertTrue(signal["oracle_actor_proxy_hit"])
        self.assertEqual("world", signal["oracle_actor_proxy_frame_space"])
        self.assertAlmostEqual(1.0, signal["structured_hazards"][0]["x"], places=5)
        self.assertAlmostEqual(0.0, signal["structured_hazards"][0]["y"], places=5)
        self.assertAlmostEqual(12.0, signal["structured_hazards"][0]["world_x"], places=5)
        self.assertAlmostEqual(2.0, signal["structured_hazards"][0]["source_rel_x"], places=5)

    def test_token_bc_alpasim_adapter_rejects_legacy_relative_oracle_proxy(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            checkpoint_path = tmp_path / "token_dagger_bc.pt"
            proxy_path = tmp_path / "oracle_actor_proxy_legacy.json"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            proxy_path.write_text(
                json.dumps(
                    {
                        "schema": "alpasim_oracle_actor_proxy_v1",
                        "frames": {
                            "1001000": {
                                "timestamp_us": 1001000,
                                "scene_id": "clipgt-oracle",
                                "hazards": [
                                    {
                                        "x": 2.0,
                                        "y": 0.0,
                                        "vx": -4.0,
                                        "vy": 0.0,
                                        "radius": 1.2,
                                        "kind": "automobile",
                                        "label": "oracle-car",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                oracle_actor_proxy_path=proxy_path,
                oracle_actor_proxy_tolerance_us=20_000,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[
                    SimpleNamespace(
                        timestamp_us=1000000,
                        pose=SimpleNamespace(
                            vec=SimpleNamespace(x=10.0, y=1.0, z=0.0),
                            quat=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
                        ),
                    )
                ],
            )

            prediction = adapter.predict(prediction_input)
            signal = json.loads(prediction.reasoning_text or "{}")["alpasim_signal"]

        self.assertFalse(signal["oracle_actor_proxy_hit"])
        self.assertEqual("legacy_relative_proxy_unsupported", signal["oracle_actor_proxy_miss_reason"])
        self.assertEqual("legacy_relative", signal["oracle_actor_proxy_frame_space"])
        self.assertEqual([], signal.get("structured_hazards", []))

    def test_token_bc_alpasim_adapter_keeps_empty_world_proxy_frames_in_world_space(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            checkpoint_path = tmp_path / "token_dagger_bc.pt"
            proxy_path = tmp_path / "oracle_actor_proxy_empty_world.json"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            last_linear = [module for module in model.modules() if isinstance(module, torch.nn.Linear)][-1]
            last_linear.bias.data[TOKEN_ORDER.index("maintain")] = 5.0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            proxy_path.write_text(
                json.dumps(
                    {
                        "schema": "alpasim_oracle_actor_proxy_v1",
                        "frames": {
                            "1001000": {
                                "timestamp_us": 1001000,
                                "scene_id": "clipgt-oracle",
                                "world_actors": [],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                oracle_actor_proxy_path=proxy_path,
                oracle_actor_proxy_tolerance_us=20_000,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[
                    SimpleNamespace(
                        timestamp_us=1000000,
                        pose=SimpleNamespace(
                            vec=SimpleNamespace(x=10.0, y=1.0, z=0.0),
                            quat=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
                        ),
                    )
                ],
            )

            prediction = adapter.predict(prediction_input)
            signal = json.loads(prediction.reasoning_text or "{}")["alpasim_signal"]

        self.assertTrue(signal["oracle_actor_proxy_hit"])
        self.assertEqual("world", signal["oracle_actor_proxy_frame_space"])
        self.assertEqual(0, signal["oracle_actor_proxy_count"])
        self.assertEqual(0, signal["oracle_actor_proxy_world_actor_count"])
        self.assertEqual([], signal.get("structured_hazards", []))

    def test_prediction_timestamp_uses_ego_history_then_camera_frames(self) -> None:
        with_ego_history = SimpleNamespace(
            ego_pose_history=[SimpleNamespace(timestamp_us=123), SimpleNamespace(timestamp_us=456)],
            camera_images={"front": [(789, np.zeros((1, 1, 3), dtype=np.uint8))]},
        )
        with_camera_only = SimpleNamespace(
            ego_pose_history=[],
            camera_images={"front": [(789, np.zeros((1, 1, 3), dtype=np.uint8))]},
        )

        self.assertEqual(456, _prediction_timestamp_us(with_ego_history))
        self.assertEqual(789, _prediction_timestamp_us(with_camera_only))

    def test_prediction_ego_pose_world_reads_current_pose(self) -> None:
        prediction_input = SimpleNamespace(
            ego_pose_history=[
                SimpleNamespace(timestamp_us=123, x=1.0, y=2.0, yaw=0.25),
                SimpleNamespace(
                    timestamp_us=456,
                    pose=SimpleNamespace(
                        vec=SimpleNamespace(x=3.0, y=4.0, z=0.0),
                        quat=SimpleNamespace(
                            x=0.0,
                            y=0.0,
                            z=float(np.sin(0.5 / 2.0)),
                            w=float(np.cos(0.5 / 2.0)),
                        ),
                    ),
                ),
            ]
        )

        pose = _prediction_ego_pose_world(prediction_input)

        self.assertIsNotNone(pose)
        assert pose is not None
        self.assertAlmostEqual(3.0, pose["world_x"])
        self.assertAlmostEqual(4.0, pose["world_y"])
        self.assertAlmostEqual(0.5, pose["world_heading"])

    def test_spotlight_adapter_rejects_stale_camera_stream_when_ego_pose_moves(self) -> None:
        model = SpotlightReflexAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        first_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
        )
        second_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1100, x=1.0, y=0.0, yaw=0.0)],
        )

        model.predict(first_input)
        with self.assertRaises(RuntimeError) as ctx:
            model.predict(second_input)

        self.assertIn("stale camera stream", str(ctx.exception))

    def test_spotlight_adapter_rejects_first_call_when_pose_time_leads_camera(self) -> None:
        model = SpotlightReflexAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=110000, x=1.0, y=0.0, yaw=0.0)],
        )

        with self.assertRaises(RuntimeError) as ctx:
            model.predict(prediction_input)

        self.assertIn("latest ego pose timestamp", str(ctx.exception))

    def test_spotlight_adapter_rejects_frozen_camera_content_when_timestamps_advance(self) -> None:
        model = SpotlightReflexAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        first_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
        )
        second_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1100, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1100, x=1.0, y=0.0, yaw=0.0)],
        )

        model.predict(first_input)
        with self.assertRaises(RuntimeError) as ctx:
            model.predict(second_input)

        self.assertIn("frozen camera stream", str(ctx.exception))

    def test_spotlight_adapter_writes_sensor_freshness_log(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "spotlight-log.jsonl"
            model = SpotlightReflexAlpaSimModel(
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                log_path=log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
                scene_id="clipgt-spotlight-log",
            )

            prediction = model.predict(prediction_input)
            reasoning = json.loads(prediction.reasoning_text or "{}")
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual("ok_initial", reasoning["sensor_freshness"]["status"])
        self.assertEqual(1, len(records))
        self.assertEqual("clipgt-spotlight-log", records[0]["scene_id"])
        self.assertEqual("ok", records[0]["result"])
        self.assertEqual("ok_initial", records[0]["sensor_freshness"]["status"])

    def test_spotlight_adapter_logs_sensor_failure_before_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "spotlight-log.jsonl"
            model = SpotlightReflexAlpaSimModel(
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                log_path=log_path,
            )
            first_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
                scene_id="clipgt-spotlight-log",
            )
            second_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[SimpleNamespace(timestamp_us=1100, x=1.0, y=0.0, yaw=0.0)],
                scene_id="clipgt-spotlight-log",
            )

            model.predict(first_input)
            with self.assertRaises(RuntimeError):
                model.predict(second_input)
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(2, len(records))
        self.assertEqual("sensor_failure", records[-1]["result"])
        self.assertEqual("stale_camera_timestamp", records[-1]["sensor_freshness"]["status"])
        self.assertIn("stale camera stream", records[-1]["sensor_error"])

    def test_spotlight_adapter_allows_advancing_camera_content_when_pose_moves(self) -> None:
        model = SpotlightReflexAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        first_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
        )
        second_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1100, image=np.full((4, 4, 3), 181, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1100, x=1.0, y=0.0, yaw=0.0)],
        )

        model.predict(first_input)
        prediction = model.predict(second_input)

        self.assertEqual((20, 2), prediction.trajectory_xy.shape)

    def test_direct_actor_planner_rejects_stale_camera_stream_when_ego_pose_moves(self) -> None:
        model = DirectActorPlannerAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        first_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 20.0, "y": 0.0, "z": 0.0},
            ],
            alpasignal={"hazards": []},
        )
        second_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1100, x=1.0, y=0.0, yaw=0.0)],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 20.0, "y": 0.0, "z": 0.0},
            ],
            alpasignal={"hazards": []},
        )

        model.predict(first_input)
        with self.assertRaises(RuntimeError) as ctx:
            model.predict(second_input)

        self.assertIn("stale camera stream", str(ctx.exception))

    def test_direct_actor_planner_rejects_first_call_when_pose_time_leads_camera(self) -> None:
        model = DirectActorPlannerAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        prediction_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=110000, x=1.0, y=0.0, yaw=0.0)],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 20.0, "y": 0.0, "z": 0.0},
            ],
            alpasignal={"hazards": []},
        )

        with self.assertRaises(RuntimeError) as ctx:
            model.predict(prediction_input)

        self.assertIn("latest ego pose timestamp", str(ctx.exception))

    def test_direct_actor_planner_log_includes_sensor_freshness(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "direct-planner-log.jsonl"
            model = DirectActorPlannerAlpaSimModel(
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                log_path=log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
                route_waypoints=[
                    {"x": 0.0, "y": 0.0, "z": 0.0},
                    {"x": 20.0, "y": 0.0, "z": 0.0},
                ],
                alpasignal={"hazards": []},
                scene_id="clipgt-direct-log",
            )

            prediction = model.predict(prediction_input)
            reasoning = json.loads(prediction.reasoning_text or "{}")
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual("ok_initial", reasoning["sensor_freshness"]["status"])
        self.assertEqual(1, len(records))
        self.assertEqual("clipgt-direct-log", records[0]["scene_id"])
        self.assertEqual("ok", records[0]["result"])
        self.assertEqual("ok_initial", records[0]["sensor_freshness"]["status"])

    def test_direct_actor_planner_rejects_frozen_camera_content_when_timestamps_advance(self) -> None:
        model = DirectActorPlannerAlpaSimModel(camera_ids=["front"], context_length=1, output_frequency_hz=4)
        first_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 20.0, "y": 0.0, "z": 0.0},
            ],
            alpasignal={"hazards": []},
        )
        second_input = SimpleNamespace(
            camera_images={"front": [SimpleNamespace(timestamp_us=1100, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
            command=DriveCommand.STRAIGHT,
            speed=6.0,
            acceleration=0.0,
            ego_pose_history=[SimpleNamespace(timestamp_us=1100, x=1.0, y=0.0, yaw=0.0)],
            route_waypoints=[
                {"x": 0.0, "y": 0.0, "z": 0.0},
                {"x": 20.0, "y": 0.0, "z": 0.0},
            ],
            alpasignal={"hazards": []},
        )

        model.predict(first_input)
        with self.assertRaises(RuntimeError) as ctx:
            model.predict(second_input)

        self.assertIn("frozen camera stream", str(ctx.exception))

    def test_token_bc_selection_log_includes_sensor_freshness(self) -> None:
        if torch is None:
            self.skipTest("torch is not installed")
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "token_dagger_bc.pt"
            selection_log_path = Path(tmp) / "selection-log.jsonl"
            model = _GeomMLP(len(TOKEN_ORDER))
            for parameter in model.parameters():
                parameter.data.zero_()
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": list(TOKEN_ORDER),
                },
                checkpoint_path,
            )
            adapter = TokenBCAlpaSimModel(
                checkpoint_path=checkpoint_path,
                device="cpu",
                camera_ids=["front"],
                context_length=1,
                output_frequency_hz=4,
                selection_log_path=selection_log_path,
            )
            prediction_input = SimpleNamespace(
                camera_images={"front": [SimpleNamespace(timestamp_us=1000, image=np.full((4, 4, 3), 180, dtype=np.uint8))]},
                command=DriveCommand.STRAIGHT,
                speed=6.0,
                acceleration=0.0,
                ego_pose_history=[SimpleNamespace(timestamp_us=1000, x=0.0, y=0.0, yaw=0.0)],
                scene_id="clipgt-tokenbc-log",
            )

            prediction = adapter.predict(prediction_input)
            reasoning = json.loads(prediction.reasoning_text or "{}")
            records = [
                json.loads(line)
                for line in selection_log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual("ok_initial", reasoning["sensor_freshness"]["status"])
        self.assertEqual(1, len(records))
        self.assertEqual("clipgt-tokenbc-log", records[0]["scene_id"])
        self.assertEqual("ok", records[0]["result"])
        self.assertEqual("ok_initial", records[0]["sensor_freshness"]["status"])

    def test_export_alpasim_audit_log_reads_spotlight_logs(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            output_dir = Path(tmp) / "audit"
            (run_dir / "driver").mkdir(parents=True)
            (run_dir / "launch-metadata.json").write_text(
                json.dumps({"model": "spotlight_reflex", "scene_preset": "fresh_3scene", "scene_ids": ["clipgt-1"]}),
                encoding="utf-8",
            )
            (run_dir / "driver" / "spotlight-log.jsonl").write_text(
                json.dumps(
                    {
                        "frame_index": 1,
                        "scene_id": "clipgt-1",
                        "command": "straight",
                        "speed_mps": 6.0,
                        "selected_maneuver": "maintain",
                        "candidate_count": 9,
                        "reference_count": 2,
                        "alpasim_signal": {"structured_hazards": [], "route_waypoints": []},
                        "sensor_freshness": {"status": "ok_initial"},
                        "result": "ok",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = export_alpasim_audit_log(run_dir, output_dir)
            frames = [
                json.loads(line)
                for line in (output_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(1, manifest["frame_count"])
        self.assertEqual(1, len(frames))
        self.assertEqual("ok_initial", frames[0]["trigger_state"]["sensor_freshness"]["status"])
        self.assertEqual("maintain", frames[0]["step"]["selected_maneuver"])

    def test_token_bc_alpasim_adapter_rejects_unknown_checkpoint_tokens(self) -> None:
        with TemporaryDirectory() as tmp:
            checkpoint_path = Path(tmp) / "bad_token_dagger_bc.pt"
            model = _GeomMLP(len(TOKEN_ORDER))
            bad_tokens = list(TOKEN_ORDER)
            bad_tokens[TOKEN_ORDER.index("maintain")] = "unknown_token"
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feat_mean": np.zeros(10, dtype=np.float32),
                    "feat_std": np.ones(10, dtype=np.float32),
                    "token_names": bad_tokens,
                },
                checkpoint_path,
            )

            with self.assertRaisesRegex(ValueError, "token_names do not match"):
                TokenBCAlpaSimModel(
                    checkpoint_path=checkpoint_path,
                    device="cpu",
                    camera_ids=["front"],
                    context_length=1,
                    output_frequency_hz=4,
                )

    def test_imports_alpasim_aggregate_text_metrics(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            aggregate_dir = run_dir / "aggregate"
            aggregate_dir.mkdir()
            metrics_file = aggregate_dir / "metrics_results.txt"
            metrics_file.write_text(
                "\n".join(
                    [
                        "Run: spotlight_reflex",
                        "n_clips: 4, n_rollouts/clip: 2",
                        "collision_at_fault        0.00 ± 0.00      MAX",
                        "offroad                   0.01 ± 0.00      MAX",
                        "dist_to_gt_trajectory     2.40 ± 0.50      MAX",
                        "safety_monitor_triggered  0.00 ± 0.00      MAX",
                    ]
                ),
                encoding="utf-8",
            )

            metrics_path, metrics, run_count = load_alpasim_metrics(run_dir)
            evidence = build_alpasim_evidence(run_dir).to_dict()

        self.assertEqual(metrics_path.name, "metrics_results.txt")
        self.assertEqual(run_count, 8)
        self.assertEqual(metrics["collision_at_fault"], 0.0)
        self.assertEqual(evidence["run_count"], 8)
        self.assertTrue(evidence["sensor_realistic"])
        self.assertFalse(evidence["official_compass_score"])
        self.assertTrue(evidence["gates"]["collision_rate"])
        self.assertTrue(evidence["gates"]["route_deviation_m"])

    def test_imports_alpasim_json_metrics(self) -> None:
        with TemporaryDirectory() as tmp:
            metrics_file = Path(tmp) / "metrics_results.json"
            metrics_file.write_text(
                """{
                  "run_count": 3,
                  "collision_at_fault": {"mean": 0.02, "std": 0.01},
                  "offroad": 0.0,
                  "dist_to_gt_trajectory": 4.0,
                  "safety_monitor_triggered": 0.0
                }""",
                encoding="utf-8",
            )

            evidence = build_alpasim_evidence(metrics_file).to_dict()

        self.assertEqual(evidence["run_count"], 3)
        self.assertFalse(evidence["gates"]["collision_rate"])
        self.assertFalse(evidence["gates"]["route_deviation_m"])

    def test_imports_alpasim_csv_metrics(self) -> None:
        with TemporaryDirectory() as tmp:
            aggregate_dir = Path(tmp) / "aggregate"
            aggregate_dir.mkdir()
            metrics_file = aggregate_dir / "metrics_results.csv"
            header = ",".join(
                [
                    "run_uuid",
                    "n_clips",
                    "n_rollouts",
                    "collision_at_fault",
                    "offroad",
                    "dist_to_gt_trajectory",
                    "safety_monitor_triggered",
                ]
            )
            metrics_file.write_text(
                "\n".join(
                    [
                        header,
                        "a,2,1,0.0,0.0,1.0,0.0",
                        "b,2,1,0.0,0.0,2.0,0.0",
                    ]
                )
            )

            evidence = build_alpasim_evidence(Path(tmp)).to_dict()

        self.assertEqual(evidence["run_count"], 4)
        self.assertEqual(evidence["metrics"]["dist_to_gt_trajectory"], 1.5)
        self.assertTrue(all(value is True for value in evidence["gates"].values()))


def _skip_torch_dependent_tests_if_needed() -> None:
    if torch is not None:
        return
    reason = "Torch environment not available for learned policy validation"
    for name in dir(AlpaSimIntegrationTests):
        if name.startswith("test_token_bc_alpasim_adapter_"):
            setattr(AlpaSimIntegrationTests, name, unittest.skip(reason)(getattr(AlpaSimIntegrationTests, name)))


_skip_torch_dependent_tests_if_needed()


if __name__ == "__main__":
    unittest.main()
