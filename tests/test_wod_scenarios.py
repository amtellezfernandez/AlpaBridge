from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wod2sim.simulator.compositional_scenarios import (
    COMPOSITIONAL_SUITES,
    generate_compositional_scenario,
)
from wod2sim.simulator.environment import (
    actor_at_tick,
    actor_to_obstacle,
    interpolate_lane,
    nearest_lane_point,
    route_centerline,
    scenario_at_state,
    scenario_at_tick,
    scenario_to_dict,
)
from wod2sim.simulator.wod_scenarios import WOD_E2E_CLUSTERS, generate_wod_scenario
from wod2sim.simulator.policy import StepRecord


class WodScenarioGeneratorTests(unittest.TestCase):
    def test_all_clusters_generate_deterministic_scenarios(self) -> None:
        for cluster in WOD_E2E_CLUSTERS:
            first = scenario_to_dict(generate_wod_scenario(cluster, seed=42))
            second = scenario_to_dict(generate_wod_scenario(cluster, seed=42))
            self.assertEqual(first, second)
            self.assertEqual(first["cluster"], cluster)
            self.assertEqual(first["tags"]["generator"], "wod_e2e_procedural_v1")
            self.assertGreaterEqual(len(first["lane_center"]), 2)
            self.assertGreater(len(first["obstacles"]), 0)
            self.assertGreater(len(first["actors"]), 0)
            self.assertIn("weather", first["environment"])
            self.assertGreater(len(first["map_features"]), 0)

    def test_invalid_cluster_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_wod_scenario("not-a-cluster", seed=1)

    def test_demo_cli_accepts_wod_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_demo.py"),
                    "--seed",
                    "3",
                    "--policy",
                    "spotlight-reflex",
                    "--scenario-cluster",
                    "spotlight",
                    "--artifacts-dir",
                    temp_dir,
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads((Path(temp_dir) / "latest_rollout.json").read_text())

        self.assertEqual(payload["architecture"]["scenario_source"], "WOD-E2E procedural cluster generator")
        self.assertEqual(payload["scenario"]["cluster"], "spotlight")
        self.assertEqual(payload["scenario"]["tags"]["generator"], "wod_e2e_procedural_v1")
        self.assertGreater(len(payload["scenario"]["actors"]), 0)
        self.assertEqual(payload["architecture"]["policy"], "spotlight-reflex")

    def test_demo_cli_accepts_showcase_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_demo.py"),
                    "--seed",
                    "3",
                    "--policy",
                    "spotlight-reflex",
                    "--scenario-cluster",
                    "spotlight",
                    "--rollout-preset",
                    "showcase-spotlight",
                    "--artifacts-dir",
                    temp_dir,
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads((Path(temp_dir) / "latest_rollout.json").read_text())

        self.assertEqual(payload["architecture"]["rollout_preset"], "showcase-spotlight")
        self.assertEqual(payload["architecture"]["policy"], "spotlight-reflex")
        self.assertTrue(payload["rollout"]["success"])
        self.assertTrue(payload["rollout"]["reached_goal"])

    def test_dynamic_actor_projection_updates_active_obstacles(self) -> None:
        scenario = generate_wod_scenario("cut-in", seed=2)
        actor = scenario.actors[0]
        projected = actor_to_obstacle(actor, tick=4)
        self.assertIsNotNone(projected)
        active = scenario_at_tick(scenario, tick=4)
        self.assertTrue(any(obstacle.kind == actor.kind for obstacle in active.obstacles))
        self.assertNotEqual((actor.x, actor.y), (projected.x, projected.y))

    def test_ambient_obstacles_are_visual_texture_not_blocking_hazards(self) -> None:
        scenario = generate_wod_scenario("construction", seed=10)
        self.assertTrue(any(obstacle.kind == "ambient" for obstacle in scenario.obstacles))
        active = scenario_at_tick(scenario, tick=0)
        self.assertFalse(any(obstacle.kind == "ambient" for obstacle in active.obstacles))

    def test_wod_smoke_seeds_have_reachable_routes_and_no_ambient_blockers(self) -> None:
        for cluster in WOD_E2E_CLUSTERS:
            for seed in (1, 2, 3):
                scenario = generate_wod_scenario(cluster, seed)
                self.assertGreater(scenario.goal[0], scenario.start[0], f"{cluster} seed {seed} route regressed")
                self.assertGreaterEqual(len(scenario.lane_center), 2)
                active = scenario_at_tick(scenario, tick=0)
                self.assertFalse(any(obstacle.kind == "ambient" for obstacle in active.obstacles))

    def test_intersection_crossing_is_delayed_until_ego_approach(self) -> None:
        scenario = generate_wod_scenario("intersection", seed=3)
        crossing_actor = next(actor for actor in scenario.actors if actor.role == "conflicting_vehicle")

        self.assertGreaterEqual(crossing_actor.active_from, 24)
        self.assertGreaterEqual(crossing_actor.speed, 2.6)
        self.assertFalse(any(obstacle.label == "conflicting_vehicle" for obstacle in scenario_at_tick(scenario, tick=0).obstacles))
        self.assertTrue(any(obstacle.label == "conflicting_vehicle" for obstacle in scenario_at_tick(scenario, tick=crossing_actor.active_from).obstacles))

    def test_intersection_conflict_actor_starts_close_enough_to_force_a_decision(self) -> None:
        scenario = generate_wod_scenario("intersection", seed=3)
        crossing_actor = next(actor for actor in scenario.actors if actor.role == "conflicting_vehicle")
        conflict_x, conflict_y = scenario.lane_center[3]
        self.assertLess(abs(crossing_actor.y - conflict_y), scenario.lane_half_width * 1.2)
        self.assertLess(abs(crossing_actor.x - conflict_x), 3.0)

    def test_intersection_actor_triggers_from_ego_position(self) -> None:
        scenario = generate_wod_scenario("intersection", seed=3)
        trigger_x = float(scenario.environment["intersection_trigger_x"])
        before_position = (trigger_x - 1.0, scenario.start[1])
        after_position = (trigger_x + 0.5, scenario.start[1])

        before_scenario, runtime = scenario_at_state(scenario, tick=20, position=before_position, runtime_state={})
        after_scenario, _ = scenario_at_state(scenario, tick=21, position=after_position, runtime_state=runtime)

        self.assertFalse(any(obstacle.label == "conflicting_vehicle" for obstacle in before_scenario.obstacles))
        self.assertTrue(any(obstacle.label == "conflicting_vehicle" for obstacle in after_scenario.obstacles))

    def test_spotlight_hazard_uses_trigger_region_metadata(self) -> None:
        scenario = generate_wod_scenario("spotlight", seed=3)
        trigger_region = scenario.environment["trigger_regions"][0]
        center_x = (float(trigger_region["x_min"]) + float(trigger_region["x_max"])) * 0.5
        before_scenario, runtime = scenario_at_state(scenario, tick=10, position=(center_x - 12.0, scenario.start[1]), runtime_state={})
        armed_scenario, runtime = scenario_at_state(scenario, tick=11, position=(center_x, scenario.start[1]), runtime_state=runtime)
        after_scenario, _ = scenario_at_state(scenario, tick=12, position=(center_x, scenario.start[1]), runtime_state=runtime)

        self.assertFalse(any(obstacle.label == "spotlight_hazard" for obstacle in before_scenario.obstacles))
        self.assertFalse(any(obstacle.label == "spotlight_hazard" for obstacle in armed_scenario.obstacles))
        self.assertTrue(any(obstacle.label == "spotlight_hazard" for obstacle in after_scenario.obstacles))

    def test_intersection_static_textures_do_not_overlap_conflict_pocket(self) -> None:
        scenario = generate_wod_scenario("intersection", seed=3)
        conflict_x, conflict_y = scenario.lane_center[3]

        nearby_static = [
            obstacle
            for obstacle in scenario.obstacles
            if obstacle.label == "cross_traffic_texture"
            and abs(obstacle.x - conflict_x) < 6.0
            and abs(obstacle.y - conflict_y) < scenario.lane_half_width * 1.35
        ]
        self.assertEqual([], nearby_static)

    def test_two_lane_scenarios_start_on_a_travel_lane_not_road_center(self) -> None:
        for cluster in ("intersection", "spotlight", "foreign object debris"):
            scenario = generate_wod_scenario(cluster, seed=3)
            self.assertNotAlmostEqual(scenario.start[1], scenario.lane_center[0][1], places=3)
            route_points = route_centerline(scenario)
            self.assertAlmostEqual(scenario.start[1], route_points[0][1], places=3)

    def test_spotlight_lane_profile_is_smooth(self) -> None:
        for seed in (1, 2, 3, 7, 11):
            scenario = generate_wod_scenario("spotlight", seed=seed)
            y_values = [point[1] for point in scenario.lane_center]
            deltas = [abs(b - a) for a, b in zip(y_values, y_values[1:])]
            self.assertLess(max(deltas), 4.5, f"spotlight seed {seed} regressed to jagged lane geometry")

    def test_evaluation_script_writes_csv_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "evaluate_scenarios.py"),
                    "--seed-start",
                    "1",
                    "--seed-end",
                    "2",
                    "--policy",
                    "spotlight-reflex",
                    "--suite",
                    "wod",
                    "--output-dir",
                    temp_dir,
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads((Path(temp_dir) / "scenario_eval.json").read_text())
            csv_text = (Path(temp_dir) / "scenario_eval.csv").read_text()

        self.assertEqual(len(payload["runs"]), len(WOD_E2E_CLUSTERS) * 2)
        self.assertIn("success_rate", payload["summary"][0])
        self.assertIn("benchmark_pass_rate_ci95_low", payload["summary"][0])
        self.assertIn("trajectory_safety_pass", payload["runs"][0])
        self.assertIn("trajectory_safety_event_count", payload["runs"][0])
        self.assertIn("curriculum", payload)
        self.assertEqual("closed-loop rollout", payload["statistics"]["unit"])
        self.assertIn("suite,cluster,topology", csv_text)

    def test_compositional_generator_emits_manifest_not_taxonomy_only(self) -> None:
        for suite in COMPOSITIONAL_SUITES:
            scenario = generate_compositional_scenario(seed=7, suite=suite)
            first = scenario_to_dict(scenario)
            second = scenario_to_dict(generate_compositional_scenario(seed=7, suite=suite))
            self.assertEqual(first, second)
            self.assertEqual(first["tags"]["generator"], "compositional_ood_v1")
            self.assertEqual(first["tags"]["scenario_suite"], suite)
            self.assertIn(first["tags"]["topology"], first["cluster"])
            self.assertIn("primary_hazard_id", first["tags"])
            self.assertIn("intended_decision", first["tags"])
            self.assertIn("allowed_maneuvers", first["tags"])
            self.assertIn("ood_axes", first["tags"])
            self.assertGreaterEqual(first["tags"]["blocking_hazards"], 1)
            self.assertGreater(len(first["map_features"]), 1)

    def test_compositional_primary_static_hazard_remains_deliberate(self) -> None:
        for seed in range(1, 30):
            scenario = generate_compositional_scenario(seed=seed, suite="compositional")
            primary_id = scenario.tags["primary_hazard_id"]
            primary = next((obstacle for obstacle in scenario.obstacles if obstacle.label == primary_id), None)
            if primary is None:
                continue
            _, _, lane_error = nearest_lane_point((primary.x, primary.y), interpolate_lane(scenario.lane_center))
            self.assertLessEqual(lane_error, scenario.lane_half_width * 0.55)
            return
        self.fail("no static primary hazard found in seed range")

    def test_compositional_adversarial_combines_hazards(self) -> None:
        scenario = generate_compositional_scenario(seed=9, suite="adversarial")
        self.assertIn("+", scenario.tags["hazard_composition"])
        self.assertIn("composed_hazards", scenario.tags["ood_axes"])
        self.assertIn(len(str(scenario.tags["hazard_composition"]).split("+")), {2, 3})
        self.assertEqual(scenario.tags["hazard_count"], len(str(scenario.tags["hazard_composition"]).split("+")))
        active = scenario_at_tick(scenario, tick=3)
        self.assertFalse(any(obstacle.kind == "ambient" for obstacle in active.obstacles))

    def test_gauntlet_is_four_hazard_quality_gated_suite(self) -> None:
        scenario = generate_compositional_scenario(seed=11, suite="gauntlet")
        composition = str(scenario.tags["hazard_composition"]).split("+")
        self.assertEqual(len(composition), 4)
        self.assertIn("synchronized_threats", scenario.tags["ood_axes"])
        self.assertEqual(scenario.tags["difficulty"], 1.0)
        self.assertLessEqual(scenario.lane_half_width, 6.2)
        self.assertGreaterEqual(scenario.tags["blocking_hazards"], 4)

    def test_compositional_includes_wrong_way_as_adversarial_hazard(self) -> None:
        found = False
        for seed in range(1, 60):
            scenario = generate_compositional_scenario(seed=seed, suite="adversarial")
            if "wrong_way_vehicle" in str(scenario.tags["hazard_composition"]):
                found = True
                self.assertTrue(any(actor.behavior == "wrong_way" for actor in scenario.actors))
                break
        self.assertTrue(found, "wrong_way_vehicle should be reachable in adversarial sampling")

    def test_dynamic_behavior_is_not_constant_velocity_for_cut_in(self) -> None:
        scenario = generate_compositional_scenario(seed=21, suite="adversarial")
        actor = next((candidate for candidate in scenario.actors if candidate.behavior == "cut_in"), None)
        if actor is None:
            self.skipTest("seed did not generate a cut-in actor")
        projected = actor_at_tick(actor, tick=8)
        constant_y = actor.y + actor.vy * 8 * 0.25
        self.assertNotAlmostEqual(projected.y, constant_y)

    def test_compositional_smoke_seeds_have_manifested_primary_decisions(self) -> None:
        for suite in ("compositional", "adversarial"):
            for seed in (1, 2, 3):
                scenario = generate_compositional_scenario(seed, suite=suite)
                self.assertIn("primary_hazard_id", scenario.tags)
                self.assertIn("primary_decision_point", {feature["kind"] for feature in scenario.map_features})
                self.assertGreaterEqual(scenario.tags["blocking_hazards"], 1)

    def test_evaluation_script_writes_compositional_suite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "evaluate_scenarios.py"),
                    "--seed-start",
                    "1",
                    "--seed-end",
                    "1",
                    "--policy",
                    "spotlight-reflex",
                    "--suite",
                    "compositional",
                    "--output-dir",
                    temp_dir,
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads((Path(temp_dir) / "scenario_eval.json").read_text())

        self.assertEqual(len(payload["runs"]), 6)
        self.assertEqual(payload["runs"][0]["suite"], "compositional")
        self.assertIn("ood_axes", payload["runs"][0])
        self.assertIn("benchmark_pass_rate", payload["summary"][0])
        self.assertIn("trajectory_safety_pass_rate", payload["summary"][0])
        self.assertEqual("closed_loop_procedural_curriculum", payload["curriculum"]["generator"])

    def test_blocked_corridor_without_physical_risk_is_not_safety_event(self) -> None:
        module = _load_evaluate_scenarios_module()
        rollout = module.Rollout(
            success=True,
            collision=False,
            reached_goal=True,
            steps=[
                StepRecord(
                    t=0,
                    x=0.0,
                    y=0.0,
                    lane_error=0.0,
                    min_obstacle_distance=2.0,
                    uncertainty=0.1,
                    collision_risk=0.2,
                    action_mode="nominal",
                    speed=1.0,
                    intervention=False,
                    corridor_blocked=True,
                )
            ],
        )

        self.assertEqual([], module._trajectory_safety_events("wod", rollout))

    def test_low_clearance_is_trajectory_safety_event(self) -> None:
        module = _load_evaluate_scenarios_module()
        rollout = module.Rollout(
            success=True,
            collision=False,
            reached_goal=True,
            steps=[
                StepRecord(
                    t=3,
                    x=0.0,
                    y=0.0,
                    lane_error=0.0,
                    min_obstacle_distance=0.4,
                    uncertainty=0.1,
                    collision_risk=0.2,
                    action_mode="nominal",
                    speed=1.0,
                    intervention=False,
                )
            ],
        )

        self.assertEqual(["t3:clearance<0.55"], module._trajectory_safety_events("wod", rollout))

    def test_high_model_risk_without_tight_clearance_is_not_safety_event(self) -> None:
        module = _load_evaluate_scenarios_module()
        rollout = module.Rollout(
            success=True,
            collision=False,
            reached_goal=True,
            steps=[
                StepRecord(
                    t=7,
                    x=0.0,
                    y=0.0,
                    lane_error=0.0,
                    min_obstacle_distance=1.15,
                    uncertainty=0.1,
                    collision_risk=0.99,
                    action_mode="guarded",
                    speed=0.5,
                    intervention=True,
                )
            ],
        )

        self.assertEqual([], module._trajectory_safety_events("wod", rollout))

    def test_extreme_risk_with_tight_clearance_is_safety_event(self) -> None:
        module = _load_evaluate_scenarios_module()
        rollout = module.Rollout(
            success=True,
            collision=False,
            reached_goal=True,
            steps=[
                StepRecord(
                    t=9,
                    x=0.0,
                    y=0.0,
                    lane_error=0.0,
                    min_obstacle_distance=0.8,
                    uncertainty=0.1,
                    collision_risk=0.98,
                    action_mode="guarded",
                    speed=0.5,
                    intervention=True,
                )
            ],
        )

        self.assertEqual(["t9:risk>=0.97"], module._trajectory_safety_events("wod", rollout))

def _load_evaluate_scenarios_module():
    import importlib.util

    script = ROOT / "scripts" / "evaluate_scenarios.py"
    spec = importlib.util.spec_from_file_location("evaluate_scenarios", script)
    if spec is None or spec.loader is None:
        raise ImportError(script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
