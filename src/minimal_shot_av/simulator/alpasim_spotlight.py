from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from alpasim_driver.models.base import (
        BaseTrajectoryModel,
        DriveCommand,
        ModelPrediction,
        PredictionInput,
    )
    from alpasim_driver.schema import ModelConfig
except ImportError:
    class DriveCommand:
        LEFT = 0
        STRAIGHT = 1
        RIGHT = 2
        UNKNOWN = 3

    class ModelPrediction:
        def __init__(self, trajectory_xy: np.ndarray, headings: np.ndarray, reasoning_text: str | None = None) -> None:
            self.trajectory_xy = trajectory_xy
            self.headings = headings
            self.reasoning_text = reasoning_text

    class BaseTrajectoryModel:
        @staticmethod
        def _compute_headings_from_trajectory(trajectory_xy: np.ndarray) -> np.ndarray:
            previous = np.zeros_like(trajectory_xy)
            previous[1:, :] = trajectory_xy[:-1, :]
            deltas = trajectory_xy - previous
            return np.arctan2(deltas[:, 1], deltas[:, 0])

        def _validate_cameras(self, camera_images: dict[str, list[Any]]) -> None:
            received = set(camera_images)
            expected = set(self.camera_ids)
            if received != expected:
                raise ValueError(f"{self.__class__.__name__} expects cameras {expected}, got {received}")

    ModelConfig = Any
    PredictionInput = Any

from .alpasim_signal import extract_alpasim_signal, scenario_from_command
from .environment import Scenario, nearest_lane_point, route_centerline, scenario_at_tick
from .perception import perceive_scene
from .spotlight_reflex import SpotlightSelection, evaluate_maneuver_candidates
from .world_model import update_world_state


class SpotlightReflexAlpaSimModel(BaseTrajectoryModel):
    """AlpaSim trajectory-model adapter for the Spotlight Reflex policy.

    AlpaSim calls model plugins with camera tensors, route command, speed, acceleration,
    and ego history. This adapter stays dependency-light but uses the available
    simulator signal: route command, dynamics, camera exposure/visibility, and any
    optional structured hazards attached by an upstream AlpaSim/AlpaSignal layer.
    """

    _DEFAULT_CAMERA_IDS = ["camera_front_wide_120fov"]
    _HORIZON_SECONDS = 5.0
    _LEGAL_TOKENS = frozenset({"stop", "crawl", "maintain", "slow_yield", "lane_recover"})
    _ROUTE_MARGIN_BUFFER_M = 0.45
    _MAX_ROUTE_DEVIATION_M = 0.75

    @classmethod
    def from_config(
        cls,
        model_cfg: ModelConfig,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "SpotlightReflexAlpaSimModel":
        return cls(
            camera_ids=camera_ids,
            context_length=context_length or 1,
            output_frequency_hz=output_frequency_hz,
        )

    def __init__(
        self,
        camera_ids: list[str] | None = None,
        context_length: int = 1,
        output_frequency_hz: int = 4,
    ) -> None:
        self._camera_ids = camera_ids or list(self._DEFAULT_CAMERA_IDS)
        self._context_length = context_length
        self._output_frequency_hz = output_frequency_hz

    @property
    def camera_ids(self) -> list[str]:
        return self._camera_ids

    @property
    def context_length(self) -> int:
        return self._context_length

    @property
    def output_frequency_hz(self) -> int:
        return self._output_frequency_hz

    def _encode_command(self, command: DriveCommand) -> str:
        return {
            DriveCommand.LEFT: "left",
            DriveCommand.STRAIGHT: "straight",
            DriveCommand.RIGHT: "right",
            DriveCommand.UNKNOWN: "straight",
        }[command]

    def predict(self, prediction_input: PredictionInput) -> ModelPrediction:
        self._validate_cameras(prediction_input.camera_images)
        for camera_id, frames in prediction_input.camera_images.items():
            if len(frames) != self._context_length:
                raise ValueError(
                    f"SpotlightReflexAlpaSimModel expects {self._context_length} "
                    f"frame(s) for {camera_id}, got {len(frames)}"
                )

        command = self._encode_command(prediction_input.command)
        speed_mps = max(0.25, float(prediction_input.speed))
        alpasim_signal = extract_alpasim_signal(prediction_input)
        scenario = scenario_from_command(command, alpasim_signal)
        active_scenario = scenario_at_tick(scenario, 0)
        position = active_scenario.start
        perception = perceive_scene(active_scenario, position)
        world_state = update_world_state(active_scenario, position, perception)
        selection = _select_legal_transfer_maneuver(
            active_scenario,
            position,
            world_state,
            perception,
            speed_mps=speed_mps,
        )

        trajectory_xy = _resample_to_frequency(
            np.asarray(selection.candidate.trajectory, dtype=np.float32),
            output_frequency_hz=self._output_frequency_hz,
            horizon_seconds=self._HORIZON_SECONDS,
        )
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        selection_metadata = selection.to_metadata()
        reasoning_text = json.dumps(
            {
                "adapter": "minimal_shot_av.simulator.spotlight_reflex",
                "command": command,
                "selected_maneuver": selection.candidate.name,
                "candidate_count": selection.candidate_count,
                "reference_count": selection.reference_count,
                "selector_score": selection.score.combined_score,
                "selector_effective_score": selection_metadata["selector_effective_score"],
                "selector_3s_score": selection.score.score_3s,
                "selector_5s_score": selection.score.score_5s,
                "selector_3s_reference": selection.score.reference_3s_label,
                "selector_5s_reference": selection.score.reference_5s_label,
                "decision_reason": selection_metadata["decision_reason"],
                "decision_reasons": selection_metadata["decision_reasons"],
                "transfer_legality_gate_applied": selection_metadata["transfer_legality_gate_applied"],
                "transfer_legality_previous_maneuver": selection_metadata["transfer_legality_previous_maneuver"],
                "transfer_legality_reason": selection_metadata["transfer_legality_reason"],
                "transfer_legality_vetoed_tokens": selection_metadata["transfer_legality_vetoed_tokens"],
                "top_candidate_summaries": selection_metadata["top_candidate_summaries"],
                "obstacle_pressure": world_state.obstacle_pressure,
                "route_blockage": world_state.route_blockage,
                "corridor_blocked": world_state.corridor_blocked,
                "left_clearance": world_state.left_clearance,
                "right_clearance": world_state.right_clearance,
                "preferred_escape_side": world_state.preferred_escape_side,
                "alpasim_signal": alpasim_signal,
            },
            sort_keys=True,
        )
        return ModelPrediction(
            trajectory_xy=trajectory_xy,
            headings=headings,
            reasoning_text=reasoning_text,
        )


def _resample_to_frequency(
    trajectory_xy: np.ndarray,
    output_frequency_hz: int,
    horizon_seconds: float,
) -> np.ndarray:
    expected_points = max(1, int(round(output_frequency_hz * horizon_seconds)))
    if expected_points == trajectory_xy.shape[0]:
        return trajectory_xy

    source_t = np.linspace(1.0 / trajectory_xy.shape[0], 1.0, trajectory_xy.shape[0])
    target_t = np.linspace(1.0 / expected_points, 1.0, expected_points)
    x = np.interp(target_t, source_t, trajectory_xy[:, 0])
    y = np.interp(target_t, source_t, trajectory_xy[:, 1])
    return np.stack((x, y), axis=1).astype(np.float32)


def _select_legal_transfer_maneuver(
    scenario: Scenario,
    position: tuple[float, float],
    world_state: Any,
    perception: Any,
    *,
    speed_mps: float,
) -> SpotlightSelection:
    evaluations, reference_count = evaluate_maneuver_candidates(
        scenario,
        position,
        world_state,
        perception,
        speed_mps,
    )
    best = max(
        evaluations,
        key=lambda item: (item.explanation.effective_score, item.candidate.confidence),
    )
    vetoes: list[dict[str, str]] = []
    safe_evaluations = []
    for evaluation in evaluations:
        violation = _transfer_legality_violation(scenario, evaluation)
        if violation is None:
            safe_evaluations.append(evaluation)
        else:
            vetoes.append({"token": evaluation.candidate.name, "reason": violation})

    chosen = best
    legality_applied = False
    legality_reason = "not_required"
    previous_maneuver = best.candidate.name
    if _transfer_legality_violation(scenario, best) is not None:
        legality_applied = True
        legality_reason = "prefer_route_stable_candidate"
        safe_pool = safe_evaluations or [
            evaluation
            for evaluation in evaluations
            if evaluation.candidate.name in SpotlightReflexAlpaSimModel._LEGAL_TOKENS
        ]
        chosen = max(
            safe_pool if safe_pool else evaluations,
            key=_transfer_legality_key,
        )
        if not safe_evaluations:
            legality_reason = "no_route_stable_candidate"

    top_candidate_summaries = tuple(
        {
            **evaluation.explanation.to_summary(),
            "transfer_legal": _transfer_legality_violation(scenario, evaluation) is None,
        }
        for evaluation in sorted(evaluations, key=lambda item: item.explanation.effective_score, reverse=True)[:3]
    )
    metadata = {
        "transfer_legality_gate_applied": legality_applied,
        "transfer_legality_previous_maneuver": previous_maneuver,
        "transfer_legality_reason": legality_reason,
        "transfer_legality_vetoed_tokens": vetoes,
    }
    return SpotlightSelection(
        chosen.candidate,
        chosen.score,
        len(evaluations),
        reference_count,
        chosen.explanation.effective_score,
        chosen.explanation.reasons,
        top_candidate_summaries,
        metadata,
    )


def _transfer_legality_violation(scenario: Scenario, evaluation: Any) -> str | None:
    token = evaluation.candidate.name
    if token not in SpotlightReflexAlpaSimModel._LEGAL_TOKENS:
        return "forbidden_lateral_maneuver"
    if evaluation.explanation.safety_penalty > 0.0:
        return "unsafe_action"
    if not evaluation.score.inside_5s_region:
        return "outside_route_region"
    lane_points = route_centerline(scenario)
    max_allowed = max(0.35, scenario.lane_half_width - SpotlightReflexAlpaSimModel._ROUTE_MARGIN_BUFFER_M)
    start_dev = _route_deviation(scenario.start, lane_points)
    final_dev = _route_deviation(evaluation.candidate.trajectory[-1], lane_points)
    if final_dev > max_allowed:
        return "lane_boundary_cross"
    if final_dev > start_dev + SpotlightReflexAlpaSimModel._MAX_ROUTE_DEVIATION_M:
        return "route_deviation_growth"
    for point in evaluation.candidate.trajectory:
        if _route_deviation(point, lane_points) > max_allowed:
            return "lane_boundary_cross"
    return None


def _route_deviation(point: tuple[float, float], lane_points: list[tuple[float, float]]) -> float:
    _, _, deviation = nearest_lane_point(point, lane_points)
    return float(deviation)


def _transfer_legality_key(evaluation: Any) -> tuple[float, ...]:
    return (
        1.0 if evaluation.score.inside_5s_region else 0.0,
        1.0 if evaluation.score.inside_3s_region else 0.0,
        1.0 if evaluation.candidate.name in SpotlightReflexAlpaSimModel._LEGAL_TOKENS else 0.0,
        -float(evaluation.explanation.near_clearance_penalty),
        float(evaluation.explanation.progress_bonus),
        float(evaluation.explanation.effective_score),
        float(evaluation.candidate.confidence),
    )
