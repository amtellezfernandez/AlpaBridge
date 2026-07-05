from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wod2sim.simulator.environment import (
    DEFAULT_EGO_RADIUS_M,
    Actor,
    Obstacle,
    Scenario,
    actor_to_obstacle_at_time,
    generate_scenario,
    interpolate_lane,
    min_segment_clearance,
    min_time_swept_clearance,
    moving_obstacle_segment_clearance,
    obstacle_signed_distance,
    scenario_at_tick,
)
from wod2sim.simulator.oracle import OracleConfig, _choose_privileged_action, run_oracle_policy
from wod2sim.simulator.perception import ScenePerception, perceive_scene
from wod2sim.simulator.planner import PlannedAction
from wod2sim.simulator.policy import EgoState, RolloutConfig, advance_ego_state, run_policy, run_spotlight_reflex_policy
from wod2sim.simulator.policy import _blocking_obstacle_row
from wod2sim.simulator.trajectory_selector import (
    TrajectoryCandidate,
    TrajectoryReference,
    score_candidate,
    speed_scale,
    trajectory_region_score,
)
from wod2sim.simulator.safety import apply_safety_filter
from wod2sim.simulator.spotlight_reflex import (
    DEFAULT_SPOTLIGHT_CONFIG,
    SimulatorBackedScoreConfig,
    SpotlightReflexConfig,
    _min_obstacle_clearance,
    _min_obstacle_clearance_with_config,
    generate_maneuver_candidates,
    select_maneuver,
)
from wod2sim.simulator.world_model import WorldState, update_world_state


SELECTOR_3S_INDEX = DEFAULT_SPOTLIGHT_CONFIG.selector.index_3s
SELECTOR_5S_INDEX = DEFAULT_SPOTLIGHT_CONFIG.selector.index_5s


def straight_trajectory(lateral_offset: float = 0.0, longitudinal_offset: float = 0.0) -> list[tuple[float, float]]:
    return [(float(index + 1) + longitudinal_offset, lateral_offset) for index in range(20)]


class TrajectorySelectorGeometryTests(unittest.TestCase):
    def test_ego_dynamics_limits_acceleration(self) -> None:
        config = RolloutConfig(dt_s=1.0, max_accel_mps2=0.5, max_decel_mps2=1.0)
        next_state = advance_ego_state(
            EgoState(x=0.0, y=0.0, heading_rad=0.0, speed_mps=0.0, steering_rad=0.0),
            (1.0, 0.0),
            2.0,
            config,
        )
        self.assertAlmostEqual(next_state.speed_mps, 0.5)
        self.assertAlmostEqual(next_state.x, 0.5)

    def test_ego_dynamics_limits_steering_rate(self) -> None:
        config = RolloutConfig(dt_s=1.0, max_accel_mps2=5.0, max_decel_mps2=5.0, max_steering_rate_rad_s=0.2)
        next_state = advance_ego_state(
            EgoState(x=0.0, y=0.0, heading_rad=0.0, speed_mps=1.0, steering_rad=0.0),
            (0.0, 1.0),
            1.0,
            config,
        )
        self.assertAlmostEqual(next_state.steering_rad, 0.2)
        self.assertGreater(next_state.heading_rad, 0.0)

    def test_segment_clearance_detects_swept_collision_between_endpoints(self) -> None:
        obstacle = Obstacle(x=0.0, y=0.0, radius=1.0)
        clearance = min_segment_clearance((-2.0, 0.0), (2.0, 0.0), [obstacle])
        self.assertLess(clearance, 0.0)

    def test_segment_clearance_uses_closest_approach_not_endpoint_distance(self) -> None:
        obstacle = Obstacle(x=2.0, y=1.0, radius=0.4)
        clearance = min_segment_clearance((0.0, 0.0), (4.0, 0.0), [obstacle])
        self.assertAlmostEqual(clearance, 0.6, places=6)

    def test_segment_clearance_shrinks_by_ego_radius(self) -> None:
        obstacle = Obstacle(x=2.0, y=1.0, radius=0.4)
        point_clearance = min_segment_clearance((0.0, 0.0), (4.0, 0.0), [obstacle])
        capsule_clearance = min_segment_clearance(
            (0.0, 0.0),
            (4.0, 0.0),
            [obstacle],
            ego_radius=DEFAULT_EGO_RADIUS_M,
        )
        self.assertAlmostEqual(capsule_clearance, point_clearance - DEFAULT_EGO_RADIUS_M, places=6)

    def test_capsule_obstacle_signed_distance_uses_length_and_heading(self) -> None:
        obstacle = Obstacle(x=0.0, y=0.0, radius=0.4, length=4.0, heading=0.0)
        signed_distance = obstacle_signed_distance((2.2, 0.0), obstacle)
        self.assertAlmostEqual(signed_distance, 0.2, places=6)

    def test_time_swept_clearance_detects_actor_crossing_between_tick_endpoints(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=100,
            actors=[
                Actor(
                    actor_id="crossing_0",
                    kind="vehicle",
                    x=0.6,
                    y=1.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=8.0,
                    vx=0.0,
                    vy=-8.0,
                    behavior="linear",
                    role="crossing_actor",
                )
            ],
        )

        clearance = min_time_swept_clearance(scenario, (0.0, 0.0), (1.35, 0.0), 0.0, 1.0)

        self.assertLess(clearance, 0.0)

    def test_relative_motion_clearance_detects_two_body_crossing(self) -> None:
        clearance = moving_obstacle_segment_clearance(
            ego_start=(0.0, 0.0),
            ego_end=(1.0, 0.0),
            obstacle_start=(1.0, 1.0),
            obstacle_end=(0.0, -1.0),
            obstacle_radius=0.2,
        )

        self.assertLess(clearance, 0.0)

    def test_relative_motion_clearance_matches_expected_separation_when_parallel(self) -> None:
        clearance = moving_obstacle_segment_clearance(
            ego_start=(0.0, 0.0),
            ego_end=(1.0, 0.0),
            obstacle_start=(0.0, 2.0),
            obstacle_end=(1.0, 2.0),
            obstacle_radius=0.5,
        )

        self.assertAlmostEqual(clearance, 1.5, places=6)

    def test_time_swept_clearance_adapts_for_nonlinear_actor_motion(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=103,
            actors=[
                Actor(
                    actor_id="erratic_0",
                    kind="pedestrian",
                    x=0.4,
                    y=-0.35,
                    width=0.8,
                    length=0.8,
                    heading=0.0,
                    speed=0.0,
                    vx=0.9,
                    vy=0.15,
                    behavior="erratic_pedestrian",
                    role="erratic_crossing",
                )
            ],
        )

        coarse = min_time_swept_clearance(
            scenario,
            (0.0, 0.0),
            (1.0, 0.0),
            0.0,
            1.0,
            samples=1,
            max_depth=0,
        )
        refined = min_time_swept_clearance(
            scenario,
            (0.0, 0.0),
            (1.0, 0.0),
            0.0,
            1.0,
            samples=1,
        )

        self.assertLessEqual(refined, coarse)

    def test_actor_projection_preserves_capsule_dimensions(self) -> None:
        actor = Actor(
            actor_id="vehicle_0",
            kind="vehicle",
            x=0.0,
            y=0.0,
            width=2.0,
            length=4.6,
            heading=math.pi / 2.0,
            speed=0.0,
            vx=0.0,
            vy=0.0,
            behavior="linear",
            role="lead_vehicle",
        )

        obstacle = actor_to_obstacle_at_time(actor, 0.0)

        assert obstacle is not None
        self.assertAlmostEqual(obstacle.radius, 1.0)
        self.assertAlmostEqual(obstacle.length or 0.0, 4.6)
        self.assertAlmostEqual(obstacle.heading, math.pi / 2.0)

    def test_perception_preserves_obstacle_shape_metadata(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[Obstacle(x=3.0, y=0.0, radius=0.5, length=4.0, heading=math.pi / 2.0)],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=104,
        )

        perception = perceive_scene(scenario, scenario.start)

        self.assertEqual(len(perception.visible_obstacles), 1)
        observed = perception.visible_obstacles[0]
        self.assertAlmostEqual(observed.length or 0.0, 4.0)
        self.assertAlmostEqual(observed.heading, math.pi / 2.0)

    def test_speed_scale_is_clipped_piecewise_linear(self) -> None:
        self.assertEqual(speed_scale(0.0), 0.5)
        self.assertEqual(speed_scale(1.4), 0.5)
        self.assertEqual(speed_scale(11.0), 1.0)
        self.assertEqual(speed_scale(15.0), 1.0)
        expected_midpoint = 0.5 + 0.5 * (6.2 - 1.4) / (11.0 - 1.4)
        self.assertAlmostEqual(speed_scale(6.2), expected_midpoint)

    def test_candidate_inside_5s_selection_region_gets_full_reference_score(self) -> None:
        reference = straight_trajectory()
        candidate = straight_trajectory(lateral_offset=1.7)
        score, inside = trajectory_region_score(candidate, reference, 91.0, 11.0, SELECTOR_5S_INDEX)
        self.assertTrue(inside)
        self.assertEqual(score, 91.0)

    def test_candidate_outside_selection_region_decays_and_floors(self) -> None:
        reference = straight_trajectory()
        candidate = straight_trajectory(lateral_offset=100.0)
        score, inside = trajectory_region_score(candidate, reference, 91.0, 11.0, SELECTOR_5S_INDEX)
        self.assertFalse(inside)
        self.assertEqual(score, 4.0)

    def test_3s_and_5s_indices_use_distinct_thresholds(self) -> None:
        reference = straight_trajectory()
        candidate = straight_trajectory()
        candidate[SELECTOR_3S_INDEX] = (reference[SELECTOR_3S_INDEX][0], 0.6)
        candidate[SELECTOR_5S_INDEX] = (reference[SELECTOR_5S_INDEX][0], 0.6)

        score_3s, inside_3s = trajectory_region_score(candidate, reference, 80.0, 1.4, SELECTOR_3S_INDEX)
        score_5s, inside_5s = trajectory_region_score(candidate, reference, 80.0, 1.4, SELECTOR_5S_INDEX)

        self.assertFalse(inside_3s)
        self.assertLess(score_3s, 80.0)
        self.assertTrue(inside_5s)
        self.assertEqual(score_5s, 80.0)

    def test_invalid_selection_region_index_raises(self) -> None:
        with self.assertRaises(ValueError):
            trajectory_region_score(straight_trajectory(), straight_trajectory(), 80.0, 5.0, 7)

    def test_score_candidate_selects_best_3s_and_5s_references(self) -> None:
        candidate = TrajectoryCandidate("candidate", straight_trajectory(lateral_offset=0.4))
        references = [
            TrajectoryReference("low", straight_trajectory(lateral_offset=3.0), 70.0),
            TrajectoryReference("high", straight_trajectory(lateral_offset=0.4), 95.0),
        ]
        score = score_candidate(candidate, references, 11.0)
        self.assertEqual(score.reference_3s_label, "high")
        self.assertEqual(score.reference_5s_label, "high")
        self.assertEqual(score.combined_score, 95.0)


class ManeuverLibraryTests(unittest.TestCase):
    def test_every_candidate_has_20_finite_points(self) -> None:
        candidates = generate_maneuver_candidates((0.0, 0.0), (1.0, 0.0), 2.0)
        self.assertEqual(len(candidates), 9)
        for candidate in candidates:
            self.assertEqual(len(candidate.trajectory), 20)
            for point in candidate.trajectory:
                self.assertTrue(math.isfinite(point[0]))
                self.assertTrue(math.isfinite(point[1]))

    def test_stop_trajectory_remains_at_current_point(self) -> None:
        candidates = generate_maneuver_candidates((2.0, -1.0), (1.0, 0.0), 2.0)
        stop = next(candidate for candidate in candidates if candidate.name == "stop")
        self.assertTrue(all(point == (2.0, -1.0) for point in stop.trajectory))

    def test_lateral_maneuvers_have_expected_sign(self) -> None:
        generated_candidates = generate_maneuver_candidates((0.0, 0.0), (1.0, 0.0), 2.0)
        candidates = {candidate.name: candidate for candidate in generated_candidates}
        self.assertGreater(candidates["nudge_left"].trajectory[-1][1], 0.0)
        self.assertLess(candidates["nudge_right"].trajectory[-1][1], 0.0)
        self.assertGreater(candidates["evasive_left"].trajectory[-1][1], candidates["nudge_left"].trajectory[-1][1])
        self.assertLess(candidates["evasive_right"].trajectory[-1][1], candidates["nudge_right"].trajectory[-1][1])

    def test_selector_prefers_lateral_avoidance_under_obstacle_pressure(self) -> None:
        scenario = Scenario(
            width=40.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (30.0, 0.0)],
            lane_half_width=5.0,
            obstacles=[Obstacle(x=4.0, y=1.0, radius=1.0)],
            start=(0.0, 0.0),
            goal=(30.0, 0.0),
            seed=123,
        )
        position = scenario.start
        perception = perceive_scene(scenario, position)
        world_state = update_world_state(scenario, position, perception)
        selection = select_maneuver(scenario, position, world_state, perception, 1.25)
        self.assertIn(selection.candidate.name, {"nudge_right", "evasive_right"})

    def test_world_geometry_summary_is_label_free(self) -> None:
        base = Scenario(
            width=40.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (20.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[Obstacle(x=5.0, y=1.0, radius=1.0, kind="unknown", label="alpha")],
            start=(0.0, 0.0),
            goal=(20.0, 0.0),
            seed=125,
            cluster="novel_object",
            tags={"source": "label_a"},
        )
        relabeled = Scenario(
            width=base.width,
            height=base.height,
            lane_center=base.lane_center,
            lane_half_width=base.lane_half_width,
            obstacles=[Obstacle(x=5.0, y=1.0, radius=1.0, kind="construction_foam", label="beta")],
            start=base.start,
            goal=base.goal,
            seed=base.seed,
            cluster="different_cluster",
            tags={"source": "label_b"},
        )

        base_state = update_world_state(base, base.start, perceive_scene(base, base.start))
        relabeled_state = update_world_state(relabeled, relabeled.start, perceive_scene(relabeled, relabeled.start))

        self.assertGreater(base_state.route_blockage, 0.45)
        self.assertTrue(base_state.corridor_blocked)
        self.assertEqual(base_state.preferred_escape_side, "right")
        self.assertAlmostEqual(base_state.obstacle_pressure, relabeled_state.obstacle_pressure)
        self.assertAlmostEqual(base_state.route_blockage, relabeled_state.route_blockage)
        self.assertEqual(base_state.corridor_blocked, relabeled_state.corridor_blocked)
        self.assertAlmostEqual(base_state.left_clearance, relabeled_state.left_clearance)
        self.assertAlmostEqual(base_state.right_clearance, relabeled_state.right_clearance)
        self.assertEqual(base_state.preferred_escape_side, relabeled_state.preferred_escape_side)

    def test_world_geometry_uses_obstacle_length_for_route_blockage(self) -> None:
        compact = Scenario(
            width=40.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (30.0, 0.0)],
            lane_half_width=3.0,
            obstacles=[Obstacle(x=6.0, y=2.7, radius=0.5, length=1.0, heading=0.0)],
            start=(0.0, 0.0),
            goal=(30.0, 0.0),
            seed=130,
        )
        elongated = Scenario(
            width=40.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (30.0, 0.0)],
            lane_half_width=3.0,
            obstacles=[Obstacle(x=6.0, y=2.7, radius=0.5, length=5.0, heading=math.pi / 2.0)],
            start=(0.0, 0.0),
            goal=(30.0, 0.0),
            seed=131,
        )

        compact_state = update_world_state(compact, compact.start, perceive_scene(compact, compact.start))
        elongated_state = update_world_state(elongated, elongated.start, perceive_scene(elongated, elongated.start))

        self.assertGreater(elongated_state.route_blockage, compact_state.route_blockage)

    def test_selector_explains_selected_maneuver_and_alternatives(self) -> None:
        scenario = Scenario(
            width=40.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (30.0, 0.0)],
            lane_half_width=5.0,
            obstacles=[Obstacle(x=4.0, y=1.0, radius=1.0)],
            start=(0.0, 0.0),
            goal=(30.0, 0.0),
            seed=124,
        )
        perception = perceive_scene(scenario, scenario.start)
        world_state = update_world_state(scenario, scenario.start, perception)

        selection = select_maneuver(scenario, scenario.start, world_state, perception, 1.25)
        metadata = selection.to_metadata()

        self.assertGreater(selection.effective_score, selection.score.combined_score - 1000.0)
        self.assertGreaterEqual(len(selection.decision_reasons), 6)
        self.assertIn("3s_reference=", selection.decision_reasons[0])
        self.assertIn("action_clearance=", " ".join(selection.decision_reasons))
        self.assertEqual(metadata["decision_reasons"], list(selection.decision_reasons))
        summaries = metadata["top_candidate_summaries"]
        self.assertIsInstance(summaries, list)
        self.assertGreaterEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["candidate"], selection.candidate.name)
        self.assertIn("effective_score", summaries[0])
        self.assertIn("action_clearance_m", summaries[0])
        self.assertIn("reasons", summaries[0])

    def test_forecast_clearance_keeps_static_obstacle_with_same_label_as_moving_actor(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[Obstacle(x=1.0, y=0.0, radius=1.0, kind="barrier", label="shared_role")],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=7,
            actors=[
                Actor(
                    actor_id="moving_0",
                    kind="vehicle",
                    x=0.0,
                    y=10.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=1.0,
                    vx=0.0,
                    vy=-1.0,
                    behavior="linear",
                    role="shared_role",
                )
            ],
        )
        active = scenario_at_tick(scenario, 0)

        self.assertLess(_min_obstacle_clearance([(1.0, 0.0)], active), 0.0)

    def test_default_clearance_does_not_use_privileged_actor_forecast(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=8,
            actors=[
                Actor(
                    actor_id="crossing_0",
                    kind="vehicle",
                    x=0.0,
                    y=1.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=4.0,
                    vx=0.0,
                    vy=-4.0,
                    behavior="linear",
                    role="crossing_actor",
                )
            ],
        )
        active = scenario_at_tick(scenario, 0)

        self.assertGreater(_min_obstacle_clearance([(0.0, 0.0)], active), 0.0)

    def test_privileged_forecast_clearance_uses_future_position_for_moving_actor(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=8,
            actors=[
                Actor(
                    actor_id="crossing_0",
                    kind="vehicle",
                    x=0.0,
                    y=1.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=4.0,
                    vx=0.0,
                    vy=-4.0,
                    behavior="linear",
                    role="crossing_actor",
                )
            ],
        )
        active = scenario_at_tick(scenario, 0)
        config = SpotlightReflexConfig(
            scoring=SimulatorBackedScoreConfig(use_privileged_actor_forecast=True)
        )

        self.assertLess(_min_obstacle_clearance_with_config([(0.0, 0.0)], active, config), 0.0)

    def test_privileged_forecast_clearance_uses_interpolated_actor_motion(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=18,
            actors=[
                Actor(
                    actor_id="crossing_1",
                    kind="vehicle",
                    x=0.0,
                    y=1.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=8.0,
                    vx=0.0,
                    vy=-8.0,
                    behavior="linear",
                    role="crossing_actor",
                )
            ],
        )
        active = scenario_at_tick(scenario, 0)
        config = SpotlightReflexConfig(
            scoring=SimulatorBackedScoreConfig(use_privileged_actor_forecast=True)
        )

        self.assertLess(_min_obstacle_clearance_with_config([(0.0, 0.0)], active, config), 0.0)

    def test_trajectory_clearance_uses_origin_to_first_point_segment(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[Obstacle(x=0.0, y=0.36, radius=0.02)],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=19,
        )
        active = scenario_at_tick(scenario, 0)
        candidates = generate_maneuver_candidates(active.start, (1.0, 0.0), 1.0)
        maintain = next(candidate for candidate in candidates if candidate.name == "maintain")

        without_origin = _min_obstacle_clearance_with_config(maintain.trajectory[:1], active, DEFAULT_SPOTLIGHT_CONFIG)
        with_origin = _min_obstacle_clearance_with_config(
            maintain.trajectory[:1],
            active,
            DEFAULT_SPOTLIGHT_CONFIG,
            origin=active.start,
        )

        self.assertGreater(without_origin, 0.0)
        self.assertLess(with_origin, 0.0)

    def test_forecast_clearance_replaces_current_moving_actor_obstacle(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=9,
            actors=[
                Actor(
                    actor_id="departing_0",
                    kind="vehicle",
                    x=0.0,
                    y=0.0,
                    width=1.0,
                    length=1.0,
                    heading=math.pi / 2.0,
                    speed=40.0,
                    vx=0.0,
                    vy=40.0,
                    behavior="linear",
                    role="departing_actor",
                )
            ],
        )
        active = scenario_at_tick(scenario, 0)

        self.assertLess(_min_obstacle_clearance([(0.0, 0.0)], active), 0.0)

    def test_lane_recovery_steers_toward_world_model_target(self) -> None:
        action = PlannedAction(direction=(1.0, 0.0), speed=1.0, mode="planned", score=0.0)
        world_state = WorldState(
            position=(0.0, 0.0),
            target_point=(3.0, 4.0),
            progress_fraction=0.0,
            collision_risk=0.0,
            goal_distance=10.0,
            uncertainty=0.1,
        )
        perception = ScenePerception(
            lane_index=0,
            lane_point=(0.0, 0.0),
            lane_error=4.0,
            lane_heading=(1.0, 0.0),
            corridor_margin=0.1,
            free_space_confidence=0.9,
            uncertainty=0.1,
            visible_obstacles=[],
        )

        safe_action = apply_safety_filter(action, world_state, perception)

        self.assertEqual(safe_action.mode, "lane_recovery")
        self.assertAlmostEqual(safe_action.direction[0], 0.6)
        self.assertAlmostEqual(safe_action.direction[1], 0.8)

    def test_blocking_obstacle_row_is_label_free(self) -> None:
        scenario = Scenario(
            width=40.0,
            height=30.0,
            lane_center=[(0.0, 0.0), (20.0, 0.0), (40.0, 0.0)],
            lane_half_width=6.0,
            obstacles=[
                Obstacle(x=20.0, y=-4.0, radius=0.9, kind="unknown", label="alpha"),
                Obstacle(x=20.3, y=0.0, radius=0.9, kind="unseen", label="beta"),
                Obstacle(x=19.8, y=4.0, radius=0.9, kind="novel", label="gamma"),
            ],
            start=(0.0, 0.0),
            goal=(40.0, 0.0),
            seed=14,
            cluster="not_intersection",
            tags={"generator": "not_wod"},
        )

        row = _blocking_obstacle_row(scenario)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertAlmostEqual(row[0], 20.03333333333333)

    def test_blocking_obstacle_row_uses_obstacle_shape_extents(self) -> None:
        scenario = Scenario(
            width=40.0,
            height=30.0,
            lane_center=[(0.0, 0.0), (20.0, 0.0), (40.0, 0.0)],
            lane_half_width=6.0,
            obstacles=[
                Obstacle(x=17.3, y=-4.0, radius=0.6, length=4.8, heading=0.0, kind="vehicle", label="left"),
                Obstacle(x=20.0, y=0.0, radius=0.6, length=4.8, heading=0.0, kind="vehicle", label="center"),
                Obstacle(x=22.7, y=4.0, radius=0.6, length=4.8, heading=0.0, kind="vehicle", label="right"),
            ],
            start=(0.0, 0.0),
            goal=(40.0, 0.0),
            seed=141,
        )

        row = _blocking_obstacle_row(scenario)

        self.assertIsNotNone(row)
        assert row is not None
        self.assertAlmostEqual(row[0], 20.0, places=1)


class DemoIntegrationTests(unittest.TestCase):
    def test_oracle_detects_swept_collision_between_ticks(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[Obstacle(x=0.6, y=0.0, radius=0.45)],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=99,
        )

        certificate = run_oracle_policy(
            scenario,
            max_steps=1,
            step_size=1.35,
            config=OracleConfig(
                speed_scales=(1.0,),
                steering_angles_rad=(0.0,),
                horizon_steps=1,
                max_steps=1,
                step_size=1.35,
            ),
        )

        self.assertTrue(certificate.rollout.collision)
        self.assertLess(certificate.min_clearance, 0.0)

    def test_oracle_detects_actor_crossing_within_tick(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=101,
            actors=[
                Actor(
                    actor_id="crossing_oracle",
                    kind="vehicle",
                    x=0.6,
                    y=1.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=8.0,
                    vx=0.0,
                    vy=-8.0,
                    behavior="linear",
                    role="crossing_actor",
                )
            ],
        )

        certificate = run_oracle_policy(
            scenario,
            max_steps=1,
            step_size=1.35,
            config=OracleConfig(
                speed_scales=(1.0,),
                steering_angles_rad=(0.0,),
                horizon_steps=1,
                max_steps=1,
                step_size=1.35,
            ),
        )

        self.assertTrue(certificate.rollout.collision)
        self.assertLess(certificate.min_clearance, 0.0)

    def test_oracle_planner_scores_current_step_crossing_not_next_step_only(self) -> None:
        scenario = Scenario(
            width=20.0,
            height=20.0,
            lane_center=[(0.0, 0.0), (10.0, 0.0)],
            lane_half_width=4.0,
            obstacles=[],
            start=(0.0, 0.0),
            goal=(10.0, 0.0),
            seed=102,
            actors=[
                Actor(
                    actor_id="planner_crossing",
                    kind="vehicle",
                    x=0.6,
                    y=1.0,
                    width=1.0,
                    length=1.0,
                    heading=-math.pi / 2.0,
                    speed=8.0,
                    vx=0.0,
                    vy=-8.0,
                    behavior="linear",
                    role="crossing_actor",
                )
            ],
        )
        config = OracleConfig(
            speed_scales=(1.0, 0.0),
            steering_angles_rad=(0.0,),
            horizon_steps=1,
            step_size=1.35,
        )

        direction, speed, mode = _choose_privileged_action(
            scenario,
            scenario.start,
            0,
            interpolate_lane(scenario.lane_center, samples_per_segment=config.lane_samples_per_segment),
            config,
            EgoState(x=scenario.start[0], y=scenario.start[1], heading_rad=0.0, speed_mps=0.0, steering_rad=0.0),
        )

        self.assertEqual(direction, (1.0, 0.0))
        self.assertEqual(speed, 0.0)
        self.assertEqual(mode, "yield")

    def test_demo_artifacts_include_spotlight_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_demo.py"),
                    "--seed",
                    "1",
                    "--policy",
                    "spotlight-reflex",
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

        self.assertEqual(payload["architecture"]["policy"], "spotlight-reflex")
        self.assertIn("simulator-native trajectory selector", payload["architecture"]["planner"])
        self.assertTrue(payload["rollout"]["success"])
        self.assertFalse(payload["rollout"]["collision"])
        self.assertTrue(payload["rollout"]["reached_goal"])
        first_step = payload["rollout"]["steps"][0]
        self.assertEqual(first_step["candidate_count"], 9)
        self.assertGreaterEqual(first_step["reference_count"], 1)
        self.assertIsInstance(first_step["selected_maneuver"], str)
        self.assertIsInstance(first_step["selector_score"], float)
        self.assertIsInstance(first_step["selector_effective_score"], float)
        self.assertIsInstance(first_step["selector_3s_reference"], str)
        self.assertIsInstance(first_step["selector_5s_reference"], str)
        self.assertIsInstance(first_step["decision_reason"], str)
        self.assertGreater(len(first_step["decision_reason"]), 0)
        self.assertIsInstance(first_step["decision_reasons"], list)
        self.assertGreaterEqual(len(first_step["decision_reasons"]), 6)
        self.assertIsInstance(first_step["top_candidate_summaries"], list)
        self.assertGreaterEqual(len(first_step["top_candidate_summaries"]), 1)
        self.assertIn("effective_score", first_step["top_candidate_summaries"][0])
        self.assertIsInstance(first_step["obstacle_pressure"], float)
        self.assertIsInstance(first_step["route_blockage"], float)
        self.assertIsInstance(first_step["corridor_blocked"], bool)
        self.assertIsInstance(first_step["preferred_escape_side"], str)
        self.assertIsInstance(first_step["world_model_summary"], str)
        self.assertIn("route_blockage=", first_step["world_model_summary"])

    def test_baseline_and_spotlight_demos_run_on_fixed_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for policy in ("baseline", "spotlight-reflex"):
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "run_demo.py"),
                        "--seed",
                        "2",
                        "--policy",
                        policy,
                        "--artifacts-dir",
                        str(Path(temp_dir) / policy),
                    ],
                    cwd=ROOT,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.assertTrue((Path(temp_dir) / policy / "latest_rollout.json").exists())

    def test_no_collision_regression_on_deterministic_simulator_seeds(self) -> None:
        for seed in (1, 2, 3):
            baseline = run_policy(generate_scenario(seed))
            spotlight = run_spotlight_reflex_policy(generate_scenario(seed))
            self.assertFalse(baseline.collision, f"baseline collided on seed {seed}")
            self.assertTrue(spotlight.success, f"spotlight-reflex did not succeed on seed {seed}")
            self.assertFalse(spotlight.collision, f"spotlight-reflex collided on seed {seed}")
            self.assertTrue(spotlight.reached_goal, f"spotlight-reflex did not reach the goal on seed {seed}")


if __name__ == "__main__":
    unittest.main()
