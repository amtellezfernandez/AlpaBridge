from __future__ import annotations

import json
import math
import os
from bisect import bisect_left
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

try:
    import torch
    import torch.nn as nn
except ImportError:  # pragma: no cover - exercised only in non-alpasim installs.
    torch = None
    nn = None

from .alpasim_signal import extract_alpasim_signal, scenario_from_command
from .alpasim_spotlight import (
    BaseTrajectoryModel,
    DriveCommand,
    ModelPrediction,
    PredictionInput,
    _resample_to_frequency,
    _SensorFreshnessGuard,
)
from .environment import (
    DEFAULT_EGO_RADIUS_M,
    SIM_TICK_DT_S,
    actor_to_obstacle_at_time,
    min_segment_clearance,
    min_time_swept_clearance,
    nearest_lane_point,
    route_centerline,
    scenario_at_tick,
    static_obstacles_at_time,
)
from .perception import perceive_scene
from .spotlight_reflex import (
    DEFAULT_SPOTLIGHT_CONFIG,
    _planning_heading,
    evaluate_maneuver_candidates,
    generate_maneuver_candidates,
)
from .world_model import update_world_state

N_FEATURES = 10
N_TOKENS = 9
HIDDEN = 256
DROPOUT = 0.15
TRAJECTORY_MODES = ("token", "longitudinal_only", "clamped_lateral")
SELECTION_MODES = ("argmax", "hybrid_veto", "axis_constrained", "axis_lexicographic", "actor_axis_constrained")
ACTOR_AXIS_CLEARANCE_CAP_M = 12.0
REAR_FLOW_TTC_THRESHOLD_S = 3.0
REAR_FLOW_MAX_REAR_GAP_M = 18.0
REAR_FLOW_MIN_CLOSING_MPS = 0.5
REAR_FLOW_MIN_EGO_SPEED_MPS = 2.0
REAR_FLOW_LATERAL_GATE_M = 3.0
REAR_FLOW_REQUIRED_SPEED_FRACTION = 0.45
ROUTE_STABLE_TOKENS = frozenset({"stop", "crawl", "maintain", "slow_yield", "lane_recover"})
TOKEN_ORDER = (
    "stop",
    "crawl",
    "maintain",
    "slow_yield",
    "nudge_left",
    "nudge_right",
    "evasive_left",
    "evasive_right",
    "lane_recover",
)


class _GeomMLP(nn.Module if nn is not None else object):
    def __init__(self, out_dim: int = N_TOKENS) -> None:
        if nn is None:
            raise ImportError("TokenBCAlpaSimModel requires torch; install with the alpasim extra.")
        super().__init__()
        self.net = nn.Sequential(
            nn.LayerNorm(N_FEATURES),
            nn.Linear(N_FEATURES, HIDDEN),
            nn.GELU(),
            nn.Dropout(DROPOUT),
            nn.Linear(HIDDEN, HIDDEN),
            nn.GELU(),
            nn.Dropout(DROPOUT),
            nn.Linear(HIDDEN, HIDDEN // 2),
            nn.GELU(),
            nn.Linear(HIDDEN // 2, out_dim),
        )

    def forward(self, x: Any) -> Any:
        return self.net(x)


class TokenBCAlpaSimModel(BaseTrajectoryModel):
    """AlpaSim adapter for trained token BC/DAgger checkpoints.

    Production configs default to CUDA so a learned AlpaSim run cannot silently fall back
    to CPU. Tests may still pass ``device="cpu"`` explicitly with a toy checkpoint.
    """

    _DEFAULT_CAMERA_IDS = ["camera_front_wide_120fov"]
    _HORIZON_SECONDS = 5.0

    @classmethod
    def from_config(
        cls,
        model_cfg: Any,
        device: Any,
        camera_ids: list[str],
        context_length: int | None,
        output_frequency_hz: int,
    ) -> "TokenBCAlpaSimModel":
        checkpoint_path = _cfg_value(model_cfg, "checkpoint_path", None)
        if not checkpoint_path:
            raise ValueError("TokenBCAlpaSimModel requires model.checkpoint_path")
        cfg_device = _cfg_value(model_cfg, "device", None)
        requested_device = str(cfg_device if cfg_device is not None else "cuda")
        trajectory_mode = os.getenv("WOD2SIM_TOKENBC_TRAJECTORY_MODE", str(_cfg_value(model_cfg, "trajectory_mode", "token")))
        max_lateral_offset_m = float(
            os.getenv("WOD2SIM_TOKENBC_MAX_LATERAL_OFFSET_M", str(_cfg_value(model_cfg, "max_lateral_offset_m", 2.0)))
        )
        selection_mode = os.getenv("WOD2SIM_TOKENBC_SELECTION_MODE", str(_cfg_value(model_cfg, "selection_mode", "argmax")))
        hybrid_top_k = int(os.getenv("WOD2SIM_TOKENBC_HYBRID_TOP_K", str(_cfg_value(model_cfg, "hybrid_top_k", 3))))
        hybrid_geo_weight = float(
            os.getenv("WOD2SIM_TOKENBC_HYBRID_GEOMETRIC_WEIGHT", str(_cfg_value(model_cfg, "hybrid_geometric_weight", 0.75)))
        )
        hybrid_policy_temperature = float(
            os.getenv(
                "WOD2SIM_TOKENBC_HYBRID_POLICY_TEMPERATURE",
                str(_cfg_value(model_cfg, "hybrid_policy_temperature", 1.0)),
            )
        )
        hybrid_veto_margin = float(
            os.getenv("WOD2SIM_TOKENBC_HYBRID_VETO_MARGIN", str(_cfg_value(model_cfg, "hybrid_veto_margin", 8.0)))
        )
        hybrid_max_geometric_rank = int(
            os.getenv(
                "WOD2SIM_TOKENBC_HYBRID_MAX_GEOMETRIC_RANK",
                str(_cfg_value(model_cfg, "hybrid_max_geometric_rank", 2)),
            )
        )
        selection_log_path = os.getenv("WOD2SIM_TOKENBC_SELECTION_LOG_PATH", str(_cfg_value(model_cfg, "selection_log_path", "")))
        oracle_actor_proxy_path = os.getenv(
            "WOD2SIM_TOKENBC_ORACLE_ACTOR_PROXY_PATH",
            str(_cfg_value(model_cfg, "oracle_actor_proxy_path", "")),
        )
        oracle_actor_proxy_tolerance_us = int(
            os.getenv(
                "WOD2SIM_TOKENBC_ORACLE_ACTOR_PROXY_TOLERANCE_US",
                str(_cfg_value(model_cfg, "oracle_actor_proxy_tolerance_us", 50_000)),
            )
        )
        return cls(
            checkpoint_path=checkpoint_path,
            device=requested_device,
            camera_ids=camera_ids,
            context_length=context_length or 1,
            output_frequency_hz=output_frequency_hz,
            trajectory_mode=trajectory_mode,
            max_lateral_offset_m=max_lateral_offset_m,
            selection_mode=selection_mode,
            hybrid_top_k=hybrid_top_k,
            hybrid_geometric_weight=hybrid_geo_weight,
            hybrid_policy_temperature=hybrid_policy_temperature,
            hybrid_veto_margin=hybrid_veto_margin,
            hybrid_max_geometric_rank=hybrid_max_geometric_rank,
            selection_log_path=selection_log_path or None,
            oracle_actor_proxy_path=oracle_actor_proxy_path or None,
            oracle_actor_proxy_tolerance_us=oracle_actor_proxy_tolerance_us,
        )

    def __init__(
        self,
        checkpoint_path: str | Path,
        *,
        device: str = "cuda",
        camera_ids: list[str] | None = None,
        context_length: int = 1,
        output_frequency_hz: int = 4,
        trajectory_mode: str = "token",
        max_lateral_offset_m: float = 2.0,
        selection_mode: str = "argmax",
        hybrid_top_k: int = 3,
        hybrid_geometric_weight: float = 0.75,
        hybrid_policy_temperature: float = 1.0,
        hybrid_veto_margin: float = 8.0,
        hybrid_max_geometric_rank: int = 2,
        selection_log_path: str | Path | None = None,
        oracle_actor_proxy_path: str | Path | None = None,
        oracle_actor_proxy_tolerance_us: int = 50_000,
    ) -> None:
        if torch is None:
            raise ImportError("TokenBCAlpaSimModel requires torch; install with the alpasim extra.")
        self._camera_ids = camera_ids or list(self._DEFAULT_CAMERA_IDS)
        self._context_length = context_length
        self._output_frequency_hz = output_frequency_hz
        self._checkpoint_path = str(checkpoint_path)
        self._device = _resolve_device(device)
        self._trajectory_mode = _resolve_trajectory_mode(trajectory_mode)
        self._max_lateral_offset_m = max(0.0, float(max_lateral_offset_m))
        self._selection_mode = _resolve_selection_mode(selection_mode)
        self._hybrid_top_k = max(1, int(hybrid_top_k))
        self._hybrid_geometric_weight = float(hybrid_geometric_weight)
        self._hybrid_policy_temperature = max(1e-3, float(hybrid_policy_temperature))
        self._hybrid_veto_margin = max(0.0, float(hybrid_veto_margin))
        self._hybrid_max_geometric_rank = max(1, int(hybrid_max_geometric_rank))
        self._selection_log_path = Path(selection_log_path).resolve() if selection_log_path else None
        self._oracle_actor_proxy_path = Path(oracle_actor_proxy_path).resolve() if oracle_actor_proxy_path else None
        self._oracle_actor_proxy_tolerance_us = max(0, int(oracle_actor_proxy_tolerance_us))
        self._oracle_actor_proxy_frames, self._oracle_actor_proxy_timestamps = _load_oracle_actor_proxy(
            self._oracle_actor_proxy_path
        )
        self._selection_log_lock = Lock()
        self._prediction_counter = 0
        self._sensor_freshness_guard = _SensorFreshnessGuard(self.__class__.__name__)
        self._model, self._feat_mean, self._feat_std, self._token_order = _load_checkpoint(
            Path(checkpoint_path),
            device=self._device,
        )

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
                    f"TokenBCAlpaSimModel expects {self._context_length} frame(s) "
                    f"for {camera_id}, got {len(frames)}"
                )
        command = self._encode_command(prediction_input.command)
        speed_mps = max(0.25, float(prediction_input.speed))
        try:
            sensor_freshness = self._sensor_freshness_guard.validate(prediction_input)
        except RuntimeError as exc:
            self._append_sensor_failure_log(
                prediction_input=prediction_input,
                command=command,
                speed_mps=speed_mps,
                sensor_freshness=self._sensor_freshness_guard.last_diagnostics(),
                error=str(exc),
            )
            raise

        sensor_alpasim_signal = extract_alpasim_signal(prediction_input)
        alpasim_signal = self._inject_oracle_actor_proxy(prediction_input, sensor_alpasim_signal)
        policy_alpasim_signal = (
            sensor_alpasim_signal if self._selection_mode == "actor_axis_constrained" else alpasim_signal
        )
        policy_scenario = scenario_from_command(command, policy_alpasim_signal)
        active_policy_scenario = scenario_at_tick(policy_scenario, 0)
        selection_scenario = scenario_from_command(command, alpasim_signal)
        active_selection_scenario = scenario_at_tick(selection_scenario, 0)
        position = active_policy_scenario.start
        policy_perception = perceive_scene(active_policy_scenario, position)
        policy_world_state = update_world_state(active_policy_scenario, position, policy_perception)
        selection_perception = perceive_scene(active_selection_scenario, position)
        selection_world_state = update_world_state(active_selection_scenario, position, selection_perception)

        features = _extract_features(policy_world_state, policy_perception, speed_mps)
        norm_features = ((features - self._feat_mean) / self._feat_std).astype(np.float32)
        with torch.no_grad():
            x = torch.from_numpy(norm_features).unsqueeze(0).to(self._device)
            logits = self._model(x).squeeze(0).detach().cpu().numpy()

        heading = _planning_heading(
            position,
            selection_world_state,
            selection_perception,
            active_selection_scenario,
            DEFAULT_SPOTLIGHT_CONFIG,
        )
        adapter_config = _adapter_spotlight_config(
            trajectory_mode=self._trajectory_mode,
            max_lateral_offset_m=self._max_lateral_offset_m,
            selection_mode=self._selection_mode,
        )
        candidates = _generate_adapter_candidates(
            position,
            heading,
            speed_mps,
            config=adapter_config,
        )
        spotlight_evaluations, reference_count = evaluate_maneuver_candidates(
            active_selection_scenario,
            position,
            selection_world_state,
            selection_perception,
            speed_mps=speed_mps,
            config=adapter_config,
        )
        axis_signals = (
            _candidate_axis_signals(
                spotlight_evaluations,
                scenario=active_selection_scenario,
                position=position,
                speed_mps=speed_mps,
                config=adapter_config,
            )
            if self._selection_mode == "actor_axis_constrained"
            else {}
        )
        selection_info = _select_token_with_mode(
            logits=logits,
            token_order=self._token_order,
            evaluations=spotlight_evaluations,
            axis_signals=axis_signals,
            selection_mode=self._selection_mode,
            hybrid_top_k=self._hybrid_top_k,
            hybrid_geometric_weight=self._hybrid_geometric_weight,
            hybrid_policy_temperature=self._hybrid_policy_temperature,
            hybrid_veto_margin=self._hybrid_veto_margin,
            hybrid_max_geometric_rank=self._hybrid_max_geometric_rank,
        )
        chosen_token = str(selection_info["hybrid_token"])
        candidate = candidates.get(chosen_token) or candidates["maintain"]
        trajectory_xy = _resample_to_frequency(
            np.asarray(candidate.trajectory, dtype=np.float32),
            output_frequency_hz=self._output_frequency_hz,
            horizon_seconds=self._HORIZON_SECONDS,
        )
        headings = self._compute_headings_from_trajectory(trajectory_xy)
        reasoning_text = json.dumps(
            {
                "adapter": "wod2sim.simulator.alpasim_token_bc",
                "checkpoint_path": self._checkpoint_path,
                "command": command,
                "selected_maneuver": chosen_token,
                "selection_mode": self._selection_mode,
                "trajectory_mode": self._trajectory_mode,
                "max_lateral_offset_m": self._max_lateral_offset_m,
                "top_logits": _top_logits(logits, self._token_order),
                "spotlight_selected_maneuver": selection_info["spotlight_token"],
                "selection_trace": selection_info,
                "reference_count": reference_count,
                "top_candidate_summaries": [
                    evaluation.explanation.to_summary()
                    for evaluation in sorted(
                        spotlight_evaluations,
                        key=lambda item: item.explanation.effective_score,
                        reverse=True,
                    )[:3]
                ],
                "obstacle_pressure": policy_world_state.obstacle_pressure,
                "route_blockage": policy_world_state.route_blockage,
                "corridor_blocked": policy_world_state.corridor_blocked,
                "left_clearance": policy_world_state.left_clearance,
                "right_clearance": policy_world_state.right_clearance,
                "preferred_escape_side": policy_world_state.preferred_escape_side,
                "alpasim_signal": alpasim_signal,
                "policy_alpasim_signal": policy_alpasim_signal,
                "actor_axis_policy_uses_oracle_actor_proxy": policy_alpasim_signal is alpasim_signal,
                "sensor_freshness": sensor_freshness,
            },
            sort_keys=True,
        )
        self._append_selection_log(
            prediction_input=prediction_input,
            command=command,
            speed_mps=speed_mps,
            selection_info=selection_info,
            logits=logits,
            spotlight_evaluations=spotlight_evaluations,
            alpasim_signal=alpasim_signal,
            sensor_freshness=sensor_freshness,
        )
        return ModelPrediction(trajectory_xy=trajectory_xy, headings=headings, reasoning_text=reasoning_text)

    def _append_selection_log(
        self,
        *,
        prediction_input: PredictionInput,
        command: str,
        speed_mps: float,
        selection_info: dict[str, Any],
        logits: np.ndarray,
        spotlight_evaluations: list[Any],
        alpasim_signal: dict[str, Any],
        sensor_freshness: dict[str, Any],
    ) -> None:
        if self._selection_log_path is None:
            return
        self._selection_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._prediction_counter += 1
        record = {
            "frame_index": self._prediction_counter,
            "scene_id": _prediction_scene_id(prediction_input),
            "command": command,
            "speed_mps": round(float(speed_mps), 4),
            "selection_mode": self._selection_mode,
            "trajectory_mode": self._trajectory_mode,
            "max_lateral_offset_m": self._max_lateral_offset_m,
            "hybrid_veto_margin": self._hybrid_veto_margin,
            "hybrid_max_geometric_rank": self._hybrid_max_geometric_rank,
            "dagger_argmax_token": selection_info["dagger_argmax_token"],
            "spotlight_token": selection_info["spotlight_token"],
            "hybrid_token": selection_info["hybrid_token"],
            "dagger_argmax_vetoed": selection_info["dagger_argmax_vetoed"],
            "used_fallback_geometric": selection_info["used_fallback_geometric"],
            "hybrid_matches_dagger": selection_info["hybrid_matches_dagger"],
            "hybrid_matches_spotlight": selection_info["hybrid_matches_spotlight"],
            "decision_type": selection_info["decision_type"],
            "dagger_topk_tokens": selection_info["dagger_topk_tokens"],
            "dagger_argmax_geo_gap": selection_info["dagger_argmax_geo_gap"],
            "dagger_argmax_geo_rank": selection_info["dagger_argmax_geo_rank"],
            "veto_margin": selection_info["veto_margin"],
            "max_geometric_rank": selection_info["max_geometric_rank"],
            "veto_reason": selection_info["veto_reason"],
            "vetoed_tokens": selection_info["vetoed_tokens"],
            "actor_route_guard_applied": selection_info.get("actor_route_guard_applied", False),
            "actor_route_guard_previous_token": selection_info.get("actor_route_guard_previous_token"),
            "actor_route_guard_reason": selection_info.get("actor_route_guard_reason"),
            "axis_signals": selection_info.get("axis_signals", {}),
            "hybrid_axis_scores": selection_info.get("hybrid_axis_scores", {}),
            "top_logits": _top_logits(logits, self._token_order),
            "spotlight_top_candidates": [
                evaluation.explanation.to_summary()
                for evaluation in sorted(
                    spotlight_evaluations,
                    key=lambda item: item.explanation.effective_score,
                    reverse=True,
                )[:3]
            ],
            "alpasim_signal": alpasim_signal,
            "sensor_freshness": sensor_freshness,
            "result": "ok",
        }
        with self._selection_log_lock:
            with self._selection_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _append_sensor_failure_log(
        self,
        *,
        prediction_input: PredictionInput,
        command: str,
        speed_mps: float,
        sensor_freshness: dict[str, Any] | None,
        error: str,
    ) -> None:
        if self._selection_log_path is None:
            return
        self._selection_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._prediction_counter += 1
        record = {
            "frame_index": self._prediction_counter,
            "scene_id": _prediction_scene_id(prediction_input),
            "command": command,
            "speed_mps": round(float(speed_mps), 4),
            "result": "sensor_failure",
            "sensor_error": error,
            "sensor_freshness": sensor_freshness,
        }
        with self._selection_log_lock:
            with self._selection_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _inject_oracle_actor_proxy(
        self,
        prediction_input: PredictionInput,
        alpasim_signal: dict[str, Any],
    ) -> dict[str, Any]:
        if self._oracle_actor_proxy_path is None:
            return alpasim_signal
        requested_timestamp = _prediction_timestamp_us(prediction_input)
        merged = dict(alpasim_signal)
        merged["oracle_actor_proxy_enabled"] = True
        merged["oracle_actor_proxy_path"] = str(self._oracle_actor_proxy_path)
        merged["oracle_actor_proxy_timestamp_us"] = requested_timestamp
        merged["oracle_actor_proxy_hit"] = False
        merged["oracle_actor_proxy_count"] = 0
        merged["oracle_actor_proxy_delta_us"] = None
        merged["oracle_actor_proxy_matched_timestamp_us"] = None
        if requested_timestamp is None:
            merged["oracle_actor_proxy_miss_reason"] = "missing_prediction_timestamp"
            return merged
        frame = _nearest_oracle_actor_proxy_frame(
            self._oracle_actor_proxy_frames,
            self._oracle_actor_proxy_timestamps,
            requested_timestamp,
            tolerance_us=self._oracle_actor_proxy_tolerance_us,
        )
        if frame is None:
            merged["oracle_actor_proxy_miss_reason"] = "timestamp_not_found"
            return merged
        hazards, transform_info = _oracle_frame_to_current_hazards(frame, prediction_input)
        if hazards is None:
            merged["oracle_actor_proxy_miss_reason"] = transform_info["miss_reason"]
            merged["oracle_actor_proxy_frame_space"] = transform_info["frame_space"]
            return merged
        merged["structured_hazards"] = list(alpasim_signal.get("structured_hazards", [])) + hazards
        matched_timestamp = int(frame.get("timestamp_us", requested_timestamp))
        merged["oracle_actor_proxy_hit"] = True
        merged["oracle_actor_proxy_count"] = len(hazards)
        merged["oracle_actor_proxy_world_actor_count"] = int(transform_info.get("world_actor_count", 0))
        merged["oracle_actor_proxy_delta_us"] = abs(matched_timestamp - requested_timestamp)
        merged["oracle_actor_proxy_matched_timestamp_us"] = matched_timestamp
        merged["oracle_actor_proxy_scene_id"] = frame.get("scene_id")
        merged["oracle_actor_proxy_frame_space"] = transform_info["frame_space"]
        merged["oracle_actor_proxy_current_ego_pose"] = transform_info.get("current_ego_pose")
        return merged


def _load_checkpoint(path: Path, *, device: str) -> tuple[_GeomMLP, np.ndarray, np.ndarray, tuple[str, ...]]:
    if not path.is_file():
        raise FileNotFoundError(f"Token BC checkpoint not found: {path}")
    payload = torch.load(path, map_location=device, weights_only=False)
    token_order = tuple(payload.get("token_names", TOKEN_ORDER))
    if len(token_order) != N_TOKENS or len(set(token_order)) != N_TOKENS:
        raise ValueError(f"expected {N_TOKENS} unique token names, got {list(token_order)}")
    expected_names = set(TOKEN_ORDER)
    if set(token_order) != expected_names:
        missing = sorted(expected_names - set(token_order))
        extra = sorted(set(token_order) - expected_names)
        raise ValueError(f"checkpoint token_names do not match adapter candidates; missing={missing}, extra={extra}")
    model = _GeomMLP(len(token_order)).to(device)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    feat_mean = np.asarray(payload["feat_mean"], dtype=np.float32)
    feat_std = np.asarray(payload["feat_std"], dtype=np.float32)
    if feat_mean.shape != (N_FEATURES,) or feat_std.shape != (N_FEATURES,):
        raise ValueError(f"expected feature normalizers of shape {(N_FEATURES,)}, got {feat_mean.shape}/{feat_std.shape}")
    return model, feat_mean, np.maximum(feat_std, 1e-6), token_order


def _resolve_trajectory_mode(mode: str) -> str:
    normalized = str(mode).strip().lower()
    if normalized not in TRAJECTORY_MODES:
        raise ValueError(f"unknown trajectory_mode={mode!r}; expected one of {TRAJECTORY_MODES}")
    return normalized


def _resolve_selection_mode(mode: str) -> str:
    normalized = str(mode).strip().lower()
    if normalized not in SELECTION_MODES:
        raise ValueError(f"unknown selection_mode={mode!r}; expected one of {SELECTION_MODES}")
    return normalized


def _adapter_spotlight_config(*, trajectory_mode: str, max_lateral_offset_m: float, selection_mode: str = "argmax") -> Any:
    config = DEFAULT_SPOTLIGHT_CONFIG
    if trajectory_mode != "token":
        adjusted_maneuvers = []
        for spec in config.maneuvers:
            lateral_offset = spec.lateral_offset_m
            if trajectory_mode == "longitudinal_only":
                lateral_offset = 0.0
            elif trajectory_mode == "clamped_lateral":
                lateral_offset = float(np.clip(lateral_offset, -max_lateral_offset_m, max_lateral_offset_m))
            adjusted_maneuvers.append(replace(spec, lateral_offset_m=lateral_offset))
        config = replace(config, maneuvers=tuple(adjusted_maneuvers))
    if selection_mode == "actor_axis_constrained":
        config = replace(config, scoring=replace(config.scoring, use_privileged_actor_forecast=True))
    return config


def _generate_adapter_candidates(
    position: tuple[float, float],
    heading: tuple[float, float],
    speed_mps: float,
    *,
    config: Any,
) -> dict[str, Any]:
    return {
        candidate.name: candidate
        for candidate in generate_maneuver_candidates(
            position,
            heading,
            speed_mps,
            config,
        )
    }


def _candidate_axis_signals(
    evaluations: list[Any],
    *,
    scenario: Any,
    position: tuple[float, float],
    speed_mps: float,
    config: Any,
) -> dict[str, dict[str, Any]]:
    static_obstacles = static_obstacles_at_time(scenario, float(scenario.environment.get("tick", 0.0)))
    lane_points = route_centerline(scenario)
    route_tangent = _route_tangent(position, lane_points)
    rear_flow_context = _rear_flow_context(
        scenario,
        position=position,
        route_tangent=route_tangent,
    )
    signals: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        candidate = evaluation.candidate
        trajectory = candidate.trajectory
        action_trajectory = trajectory[: config.trajectory.action_index + 1]
        route_start_deviation = _point_route_deviation(position, lane_points)
        route_final_deviation = _point_route_deviation(trajectory[-1], lane_points) if trajectory else route_start_deviation
        lane_margin = _trajectory_lane_margin(
            trajectory,
            lane_points=lane_points,
            lane_half_width=float(scenario.lane_half_width),
        )
        lane_start_margin = float(scenario.lane_half_width) - route_start_deviation
        lane_final_margin = float(scenario.lane_half_width) - route_final_deviation
        route_deviation = _trajectory_route_deviation(
            trajectory,
            lane_points=lane_points,
        )
        route_source = str(getattr(scenario, "tags", {}).get("route_source", "command_proxy"))
        route_waypoint_count = int(str(getattr(scenario, "tags", {}).get("route_waypoint_count", "0")) or "0")
        route_deviation_max = float(scenario.lane_half_width) * (0.8 if route_source == "alpasim_waypoints" else 1.0)
        candidate_forward_progress = _trajectory_forward_progress(trajectory, position, route_tangent)
        candidate_mean_speed = candidate_forward_progress / max(1e-6, float(config.trajectory.horizon_seconds))
        rear_flow = _candidate_rear_flow_metrics(
            rear_flow_context,
            speed_mps=speed_mps,
            candidate_mean_speed_mps=candidate_mean_speed,
        )
        rear_flow_required_speed = max(1.5, float(speed_mps) * REAR_FLOW_REQUIRED_SPEED_FRACTION)
        rear_flow_risk = bool(
            rear_flow["rear_flow_active"]
            and candidate_mean_speed < rear_flow_required_speed
        )
        signals[candidate.name] = {
            "actor_count": len(getattr(scenario, "actors", []) or []),
            "actor_forecast_mode": "time_swept" if config.scoring.use_privileged_actor_forecast else "frozen",
            "route_source": route_source,
            "route_waypoint_count": route_waypoint_count,
            "actor_action_clearance_m": _trajectory_actor_clearance(
                action_trajectory,
                scenario=scenario,
                config=config,
                origin=position,
            ),
            "actor_horizon_clearance_m": _trajectory_actor_clearance(
                trajectory,
                scenario=scenario,
                config=config,
                origin=position,
            ),
            "static_action_clearance_m": _trajectory_static_clearance(
                action_trajectory,
                static_obstacles=static_obstacles,
                origin=position,
            ),
            "static_horizon_clearance_m": _trajectory_static_clearance(
                trajectory,
                static_obstacles=static_obstacles,
                origin=position,
            ),
            "lane_start_margin_m": lane_start_margin,
            "lane_margin_m": lane_margin,
            "lane_final_margin_m": lane_final_margin,
            "route_start_deviation_m": route_start_deviation,
            "route_deviation_m": route_deviation,
            "route_final_deviation_m": route_final_deviation,
            "route_recovery_m": route_start_deviation - route_final_deviation,
            "route_inside_3s": bool(evaluation.score.inside_3s_region),
            "route_inside_5s": bool(evaluation.score.inside_5s_region),
            "candidate_forward_progress_m": candidate_forward_progress,
            "candidate_mean_forward_speed_mps": candidate_mean_speed,
            "rear_actor_count": rear_flow["rear_actor_count"],
            "rear_closing_actor_count": rear_flow["rear_closing_actor_count"],
            "rear_flow_gap_m": rear_flow["rear_flow_gap_m"],
            "rear_flow_ttc_s": rear_flow["rear_flow_ttc_s"],
            "rear_flow_ttc_threshold_s": REAR_FLOW_TTC_THRESHOLD_S,
            "rear_flow_required_speed_mps": rear_flow_required_speed,
            "rear_flow_risk": rear_flow_risk,
            "progress_bonus": float(evaluation.explanation.progress_bonus),
            "selector_effective_score": float(evaluation.explanation.effective_score),
            "safety_penalty": float(evaluation.explanation.safety_penalty),
            "stop_penalty": float(evaluation.explanation.stop_penalty),
            "actor_action_clearance_min_m": float(config.scoring.min_action_clearance_m),
            "actor_horizon_clearance_min_m": float(config.scoring.horizon_clearance_target_m),
            "static_action_clearance_min_m": float(config.scoring.min_action_clearance_m),
            "lane_margin_min_m": 0.0,
            "route_deviation_max_m": route_deviation_max,
        }
    return signals


def _trajectory_actor_clearance(
    trajectory: list[tuple[float, float]],
    *,
    scenario: Any,
    config: Any,
    origin: tuple[float, float],
) -> float:
    if not getattr(scenario, "actors", None):
        return math.inf
    if bool(getattr(config.scoring, "use_privileged_actor_forecast", False)):
        actor_only_scenario = replace(scenario, obstacles=[])
        current_tick = float(scenario.environment.get("tick", 0.0))
        min_clearance = math.inf
        previous_point = origin
        point_count = max(1, int(config.trajectory.point_count))
        horizon_seconds = float(config.trajectory.horizon_seconds)
        for point_index, point in enumerate(trajectory):
            segment_start_tick = current_tick + (point_index / point_count) * horizon_seconds / SIM_TICK_DT_S
            segment_end_tick = current_tick + ((point_index + 1) / point_count) * horizon_seconds / SIM_TICK_DT_S
            min_clearance = min(
                min_clearance,
                min_time_swept_clearance(
                    actor_only_scenario,
                    previous_point,
                    point,
                    segment_start_tick,
                    segment_end_tick,
                    ego_radius=DEFAULT_EGO_RADIUS_M,
                ),
            )
            previous_point = point
        return min_clearance
    current_tick = float(scenario.environment.get("tick", 0.0))
    actor_obstacles = [
        obstacle
        for actor in scenario.actors
        if (obstacle := actor_to_obstacle_at_time(actor, current_tick)) is not None
    ]
    return _trajectory_static_clearance(
        trajectory,
        static_obstacles=actor_obstacles,
        origin=origin,
    )


def _trajectory_static_clearance(
    trajectory: list[tuple[float, float]],
    *,
    static_obstacles: list[Any],
    origin: tuple[float, float],
) -> float:
    if not static_obstacles:
        return math.inf
    min_clearance = math.inf
    previous_point = origin
    for point in trajectory:
        min_clearance = min(
            min_clearance,
            min_segment_clearance(previous_point, point, static_obstacles, ego_radius=DEFAULT_EGO_RADIUS_M),
        )
        previous_point = point
    return min_clearance


def _trajectory_lane_margin(
    trajectory: list[tuple[float, float]],
    *,
    lane_points: list[tuple[float, float]],
    lane_half_width: float,
) -> float:
    min_margin = math.inf
    for point in trajectory:
        _, _, lane_error = nearest_lane_point(point, lane_points)
        min_margin = min(min_margin, lane_half_width - float(lane_error))
    return min_margin


def _point_route_deviation(point: tuple[float, float], lane_points: list[tuple[float, float]]) -> float:
    _, _, lane_error = nearest_lane_point(point, lane_points)
    return float(lane_error)


def _trajectory_route_deviation(
    trajectory: list[tuple[float, float]],
    *,
    lane_points: list[tuple[float, float]],
) -> float:
    max_deviation = 0.0
    for point in trajectory:
        _, _, lane_error = nearest_lane_point(point, lane_points)
        max_deviation = max(max_deviation, float(lane_error))
    return max_deviation


def _route_tangent(point: tuple[float, float], lane_points: list[tuple[float, float]]) -> tuple[float, float]:
    if len(lane_points) < 2:
        return (1.0, 0.0)
    index, _, _ = nearest_lane_point(point, lane_points)
    if index <= 0:
        start, end = lane_points[0], lane_points[1]
    elif index >= len(lane_points) - 1:
        start, end = lane_points[-2], lane_points[-1]
    else:
        start, end = lane_points[index - 1], lane_points[index + 1]
    return _normalize_pair((end[0] - start[0], end[1] - start[1]))


def _trajectory_forward_progress(
    trajectory: list[tuple[float, float]],
    position: tuple[float, float],
    route_tangent: tuple[float, float],
) -> float:
    if not trajectory:
        return 0.0
    dx = float(trajectory[-1][0]) - float(position[0])
    dy = float(trajectory[-1][1]) - float(position[1])
    return max(0.0, dx * route_tangent[0] + dy * route_tangent[1])


def _rear_flow_context(
    scenario: Any,
    *,
    position: tuple[float, float],
    route_tangent: tuple[float, float],
) -> dict[str, Any]:
    actors = getattr(scenario, "actors", []) or []
    current_tick = float(getattr(scenario, "environment", {}).get("tick", 0.0))
    lane_half_width = float(getattr(scenario, "lane_half_width", REAR_FLOW_LATERAL_GATE_M))
    lateral_gate = min(max(1.5, lane_half_width + 0.25), REAR_FLOW_LATERAL_GATE_M)
    route_left = (-route_tangent[1], route_tangent[0])
    rear_actor_states: list[dict[str, float]] = []
    min_gap = math.inf

    for actor in actors:
        obstacle = actor_to_obstacle_at_time(actor, current_tick)
        if obstacle is None:
            continue
        rel_forward_speed = float(actor.vx) * route_tangent[0] + float(actor.vy) * route_tangent[1]
        state = _rear_flow_obstacle_state(
            obstacle,
            position=position,
            route_tangent=route_tangent,
            route_left=route_left,
            lateral_gate=lateral_gate,
            rel_forward_speed=rel_forward_speed,
        )
        if state is None:
            continue
        rear_actor_states.append(state)
        min_gap = min(min_gap, state["gap_m"])

    for obstacle in static_obstacles_at_time(scenario, current_tick):
        if not _rear_flow_vehicle_like_obstacle(obstacle):
            continue
        state = _rear_flow_obstacle_state(
            obstacle,
            position=position,
            route_tangent=route_tangent,
            route_left=route_left,
            lateral_gate=lateral_gate,
            rel_forward_speed=0.0,
        )
        if state is None:
            continue
        rear_actor_states.append(state)
        min_gap = min(min_gap, state["gap_m"])

    return {
        "rear_actor_states": tuple(rear_actor_states),
        "rear_actor_count": len(rear_actor_states),
        "rear_flow_gap_m": min_gap,
    }


def _rear_flow_obstacle_state(
    obstacle: Any,
    *,
    position: tuple[float, float],
    route_tangent: tuple[float, float],
    route_left: tuple[float, float],
    lateral_gate: float,
    rel_forward_speed: float,
) -> dict[str, float] | None:
    dx = float(obstacle.x) - float(position[0])
    dy = float(obstacle.y) - float(position[1])
    longitudinal = dx * route_tangent[0] + dy * route_tangent[1]
    lateral = dx * route_left[0] + dy * route_left[1]
    if longitudinal >= -0.5 or abs(lateral) > lateral_gate:
        return None
    half_length = float(obstacle.length) * 0.5 if obstacle.length is not None else float(obstacle.radius)
    gap = max(0.0, -longitudinal - half_length - DEFAULT_EGO_RADIUS_M)
    if gap > REAR_FLOW_MAX_REAR_GAP_M:
        return None
    return {"gap_m": gap, "rel_forward_speed_mps": float(rel_forward_speed)}


def _rear_flow_vehicle_like_obstacle(obstacle: Any) -> bool:
    label = f"{getattr(obstacle, 'kind', '')} {getattr(obstacle, 'label', '')}".lower()
    return any(token in label for token in ("vehicle", "car", "truck", "bus", "van", "actor", "traffic"))


def _candidate_rear_flow_metrics(
    rear_flow_context: dict[str, Any],
    *,
    speed_mps: float,
    candidate_mean_speed_mps: float,
) -> dict[str, float | int | bool]:
    rear_actor_states = rear_flow_context.get("rear_actor_states", ())
    rear_actor_count = int(rear_flow_context.get("rear_actor_count", 0))
    min_gap = float(rear_flow_context.get("rear_flow_gap_m", math.inf))
    min_ttc = math.inf
    rear_closing_actor_count = 0
    for state in rear_actor_states:
        gap = float(state["gap_m"])
        rel_forward_speed = float(state["rel_forward_speed_mps"])
        candidate_closing_speed = float(speed_mps) + rel_forward_speed - float(candidate_mean_speed_mps)
        if candidate_closing_speed < REAR_FLOW_MIN_CLOSING_MPS:
            continue
        rear_closing_actor_count += 1
        min_gap = min(min_gap, gap)
        min_ttc = min(min_ttc, gap / max(candidate_closing_speed, 1e-6))

    active = bool(
        float(speed_mps) >= REAR_FLOW_MIN_EGO_SPEED_MPS
        and rear_closing_actor_count > 0
        and min_ttc <= REAR_FLOW_TTC_THRESHOLD_S
    )
    return {
        "rear_actor_count": rear_actor_count,
        "rear_closing_actor_count": rear_closing_actor_count,
        "rear_flow_gap_m": min_gap,
        "rear_flow_ttc_s": min_ttc,
        "rear_flow_active": active,
    }


def _normalize_pair(vector: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(float(vector[0]), float(vector[1]))
    if norm <= 1e-9:
        return (1.0, 0.0)
    return (float(vector[0]) / norm, float(vector[1]) / norm)


def _resolve_device(device: str) -> str:
    requested = str(device).strip().lower()
    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        raise RuntimeError("CUDA is unavailable; pass device='cpu' explicitly only for local smoke tests.")
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested for TokenBCAlpaSimModel but is not available.")
    return requested


def _extract_features(world_state: Any, perception: Any, speed_mps: float) -> np.ndarray:
    escape = {"left": -1.0, "right": 1.0, "balanced": 0.0}.get(
        str(getattr(world_state, "preferred_escape_side", "balanced")).lower(),
        0.0,
    )
    min_obstacle_distance = min(
        (
            float(getattr(obstacle, "signed_distance", 20.0))
            for obstacle in getattr(perception, "visible_obstacles", [])
        ),
        default=20.0,
    )
    return np.array(
        [
            float(getattr(world_state, "obstacle_pressure", 0.0)),
            float(getattr(world_state, "route_blockage", 0.0)),
            float(getattr(world_state, "corridor_blocked", False)),
            min(float(getattr(world_state, "left_clearance", 20.0)), 20.0),
            min(float(getattr(world_state, "right_clearance", 20.0)), 20.0),
            escape,
            float(speed_mps),
            float(getattr(perception, "lane_error", 0.0)),
            float(max(getattr(world_state, "uncertainty", 0.0), getattr(perception, "uncertainty", 0.0))),
            min(min_obstacle_distance, 20.0),
        ],
        dtype=np.float32,
    )


def _select_token_with_mode(
    *,
    logits: np.ndarray,
    token_order: tuple[str, ...],
    evaluations: list[Any],
    axis_signals: dict[str, dict[str, Any]],
    selection_mode: str,
    hybrid_top_k: int,
    hybrid_geometric_weight: float,
    hybrid_policy_temperature: float,
    hybrid_veto_margin: float,
    hybrid_max_geometric_rank: int,
) -> dict[str, Any]:
    raw_idx = int(np.argmax(logits))
    raw_token = str(token_order[raw_idx])
    spotlight_eval_by_name = {evaluation.candidate.name: evaluation for evaluation in evaluations}
    safe_global = [
        evaluation
        for evaluation in evaluations
        if evaluation.explanation.safety_penalty <= 0.0
    ]
    safe_ordered = sorted(
        safe_global if safe_global else evaluations,
        key=lambda item: (item.explanation.effective_score, item.candidate.confidence),
        reverse=True,
    )
    geometric_ranks = {evaluation.candidate.name: rank + 1 for rank, evaluation in enumerate(safe_ordered)}
    best_geometric_score = float(safe_ordered[0].explanation.effective_score)
    spotlight_best = max(
        evaluations,
        key=lambda item: (item.explanation.effective_score, item.candidate.confidence),
    )
    spotlight_token = str(spotlight_best.candidate.name)
    raw_evaluation = spotlight_eval_by_name.get(raw_token)
    if raw_evaluation is None:
        raise ValueError(f"checkpoint selected token {raw_token!r}, but no matching candidate exists")
    if selection_mode == "argmax":
        return _selection_record(
            token_order=token_order,
            raw_idx=raw_idx,
            chosen_idx=raw_idx,
            spotlight_token=spotlight_token,
            topk_indices=[raw_idx],
            safe_topk_indices=[raw_idx] if raw_evaluation.explanation.safety_penalty <= 0.0 else [],
            used_fallback_geometric=False,
            dagger_argmax_vetoed=False,
            hybrid_policy_scores={raw_token: 0.0},
            hybrid_geometric_scores={raw_token: float(raw_evaluation.explanation.effective_score)},
            dagger_argmax_geo_gap=max(0.0, best_geometric_score - float(raw_evaluation.explanation.effective_score)),
            dagger_argmax_geo_rank=int(geometric_ranks.get(raw_token, len(safe_ordered) + 1)),
            veto_margin=hybrid_veto_margin,
            max_geometric_rank=hybrid_max_geometric_rank,
            veto_reason="none",
            vetoed_tokens=[],
        )

    scaled_logits = logits.astype(np.float64) / hybrid_policy_temperature
    policy_log_probs = scaled_logits - _logsumexp(scaled_logits)
    sorted_indices = list(np.argsort(logits)[::-1])
    topk_indices = sorted_indices[: max(1, min(hybrid_top_k, len(sorted_indices)))]
    if selection_mode == "actor_axis_constrained":
        return _select_actor_axis_constrained(
            token_order=token_order,
            raw_idx=raw_idx,
            topk_indices=topk_indices,
            policy_log_probs=policy_log_probs,
            evaluations=evaluations,
            spotlight_eval_by_name=spotlight_eval_by_name,
            axis_signals=axis_signals,
            geometric_scores={
                evaluation.candidate.name: float(evaluation.explanation.effective_score)
                for evaluation in evaluations
            },
            geometric_ranks=geometric_ranks,
            best_geometric_score=best_geometric_score,
            spotlight_token=spotlight_token,
            veto_margin=hybrid_veto_margin,
            max_geometric_rank=hybrid_max_geometric_rank,
        )
    if selection_mode == "axis_constrained":
        return _select_axis_constrained(
            token_order=token_order,
            raw_idx=raw_idx,
            topk_indices=topk_indices,
            policy_log_probs=policy_log_probs,
            evaluations=evaluations,
            spotlight_eval_by_name=spotlight_eval_by_name,
            geometric_scores={
                evaluation.candidate.name: float(evaluation.explanation.effective_score)
                for evaluation in evaluations
            },
            geometric_ranks=geometric_ranks,
            best_geometric_score=best_geometric_score,
            spotlight_token=spotlight_token,
            veto_margin=hybrid_veto_margin,
            max_geometric_rank=hybrid_max_geometric_rank,
        )
    if selection_mode == "axis_lexicographic":
        return _select_axis_lexicographic(
            token_order=token_order,
            raw_idx=raw_idx,
            topk_indices=topk_indices,
            policy_log_probs=policy_log_probs,
            evaluations=evaluations,
            spotlight_eval_by_name=spotlight_eval_by_name,
            geometric_scores={
                evaluation.candidate.name: float(evaluation.explanation.effective_score)
                for evaluation in evaluations
            },
            geometric_ranks=geometric_ranks,
            best_geometric_score=best_geometric_score,
            spotlight_token=spotlight_token,
            veto_margin=hybrid_veto_margin,
            max_geometric_rank=hybrid_max_geometric_rank,
        )

    safe_topk_indices: list[int] = []
    vetoed_tokens: list[dict[str, Any]] = []
    raw_veto_reason = "none"
    for idx in topk_indices:
        token = str(token_order[idx])
        evaluation = spotlight_eval_by_name.get(token)
        if evaluation is None:
            vetoed_tokens.append({"token": token, "reason": "missing_evaluation"})
            if idx == raw_idx:
                raw_veto_reason = "missing_evaluation"
            continue
        if evaluation.explanation.safety_penalty > 0.0:
            vetoed_tokens.append({"token": token, "reason": "unsafe_action"})
            if idx == raw_idx:
                raw_veto_reason = "unsafe_action"
            continue
        geo_score = float(evaluation.explanation.effective_score)
        geo_gap = max(0.0, best_geometric_score - geo_score)
        geo_rank = int(geometric_ranks.get(token, len(safe_ordered) + 1))
        if geo_gap > hybrid_veto_margin:
            vetoed_tokens.append({"token": token, "reason": "geometric_gap", "geo_gap": round(geo_gap, 4)})
            if idx == raw_idx:
                raw_veto_reason = "geometric_gap"
            continue
        if geo_rank > hybrid_max_geometric_rank:
            vetoed_tokens.append({"token": token, "reason": "geometric_rank", "geo_rank": geo_rank})
            if idx == raw_idx:
                raw_veto_reason = "geometric_rank"
            continue
        safe_topk_indices.append(idx)
    used_fallback_geometric = False
    dagger_argmax_vetoed = raw_idx not in safe_topk_indices
    geometric_scores = {
        evaluation.candidate.name: float(evaluation.explanation.effective_score) for evaluation in evaluations
    }

    if safe_topk_indices:
        geo_values = np.array([geometric_scores[str(token_order[idx])] for idx in safe_topk_indices], dtype=np.float64)
        geo_norm = (geo_values - geo_values.mean()) / max(float(geo_values.std()), 1e-6)
        combined = np.array([policy_log_probs[idx] for idx in safe_topk_indices], dtype=np.float64) + hybrid_geometric_weight * geo_norm
        chosen_idx = int(safe_topk_indices[int(np.argmax(combined))])
    else:
        fallback_eval = max(
            safe_global if safe_global else evaluations,
            key=lambda item: (item.explanation.effective_score, item.candidate.confidence),
        )
        chosen_idx = int(token_order.index(fallback_eval.candidate.name))
        used_fallback_geometric = True

    return _selection_record(
        token_order=token_order,
        raw_idx=raw_idx,
        chosen_idx=chosen_idx,
        spotlight_token=spotlight_token,
        topk_indices=topk_indices,
        safe_topk_indices=safe_topk_indices,
        used_fallback_geometric=used_fallback_geometric,
        dagger_argmax_vetoed=dagger_argmax_vetoed,
        hybrid_policy_scores={str(token_order[idx]): round(float(policy_log_probs[idx]), 4) for idx in topk_indices},
        hybrid_geometric_scores={str(token_order[idx]): round(float(geometric_scores[str(token_order[idx])]), 4) for idx in topk_indices},
        dagger_argmax_geo_gap=max(0.0, best_geometric_score - float(geometric_scores[raw_token])),
        dagger_argmax_geo_rank=int(geometric_ranks.get(raw_token, len(safe_ordered) + 1)),
        veto_margin=hybrid_veto_margin,
        max_geometric_rank=hybrid_max_geometric_rank,
        veto_reason=raw_veto_reason,
        vetoed_tokens=vetoed_tokens,
    )


def _select_actor_axis_constrained(
    *,
    token_order: tuple[str, ...],
    raw_idx: int,
    topk_indices: list[int],
    policy_log_probs: np.ndarray,
    evaluations: list[Any],
    spotlight_eval_by_name: dict[str, Any],
    axis_signals: dict[str, dict[str, Any]],
    geometric_scores: dict[str, float],
    geometric_ranks: dict[str, int],
    best_geometric_score: float,
    spotlight_token: str,
    veto_margin: float,
    max_geometric_rank: int,
) -> dict[str, Any]:
    base_record = _select_axis_constrained(
        token_order=token_order,
        raw_idx=raw_idx,
        topk_indices=topk_indices,
        policy_log_probs=policy_log_probs,
        evaluations=evaluations,
        spotlight_eval_by_name=spotlight_eval_by_name,
        geometric_scores=geometric_scores,
        geometric_ranks=geometric_ranks,
        best_geometric_score=best_geometric_score,
        spotlight_token=spotlight_token,
        veto_margin=veto_margin,
        max_geometric_rank=max_geometric_rank,
    )
    actor_axis_scores = {
        str(token_order[idx]): _actor_axis_score_summary(
            spotlight_eval_by_name[str(token_order[idx])],
            axis_signals.get(str(token_order[idx]), {}),
            float(policy_log_probs[idx]),
        )
        for idx in topk_indices
    }
    base_chosen_token = str(base_record["hybrid_token"])
    if not _actor_axis_route_guard_required(base_chosen_token, spotlight_eval_by_name, axis_signals):
        base_record["axis_signals"] = _selection_axis_signals(axis_signals)
        base_record["hybrid_axis_scores"] = actor_axis_scores
        base_record["actor_route_guard_applied"] = False
        base_record["actor_route_guard_previous_token"] = base_chosen_token
        base_record["actor_route_guard_reason"] = "not_required"
        return base_record

    stable_topk_indices, stable_vetoes = _actor_route_stable_candidates(
        token_order=token_order,
        candidate_indices=topk_indices,
        spotlight_eval_by_name=spotlight_eval_by_name,
        axis_signals=axis_signals,
    )
    used_fallback_geometric = False
    if stable_topk_indices:
        chosen_idx = int(
            max(
                stable_topk_indices,
                key=lambda idx: _actor_route_stable_key(
                    spotlight_eval_by_name[str(token_order[idx])],
                    axis_signals[str(token_order[idx])],
                    float(policy_log_probs[idx]),
                ),
            )
        )
        safe_indices = stable_topk_indices
    else:
        all_indices = [int(token_order.index(evaluation.candidate.name)) for evaluation in evaluations]
        stable_all_indices, stable_all_vetoes = _actor_route_stable_candidates(
            token_order=token_order,
            candidate_indices=all_indices,
            spotlight_eval_by_name=spotlight_eval_by_name,
            axis_signals=axis_signals,
        )
        stable_vetoes.extend(stable_all_vetoes)
        if stable_all_indices:
            chosen_idx = int(
                max(
                    stable_all_indices,
                    key=lambda idx: _actor_route_stable_key(
                        spotlight_eval_by_name[str(token_order[idx])],
                        axis_signals[str(token_order[idx])],
                        float(policy_log_probs[idx]),
                    ),
                )
            )
            safe_indices = stable_all_indices
            used_fallback_geometric = True
        else:
            base_record["axis_signals"] = _selection_axis_signals(axis_signals)
            base_record["hybrid_axis_scores"] = actor_axis_scores
            base_record["actor_route_guard_applied"] = False
            base_record["actor_route_guard_previous_token"] = base_chosen_token
            base_record["actor_route_guard_reason"] = "no_route_stable_actor_safe_candidate"
            base_record["actor_route_guard_vetoed_tokens"] = stable_vetoes
            return base_record

    raw_token = str(token_order[raw_idx])
    record = _selection_record(
        token_order=token_order,
        raw_idx=raw_idx,
        chosen_idx=chosen_idx,
        spotlight_token=spotlight_token,
        topk_indices=topk_indices,
        safe_topk_indices=safe_indices,
        used_fallback_geometric=used_fallback_geometric,
        dagger_argmax_vetoed=raw_idx not in safe_indices,
        hybrid_policy_scores={str(token_order[idx]): round(float(policy_log_probs[idx]), 4) for idx in topk_indices},
        hybrid_geometric_scores={
            str(token_order[idx]): round(float(geometric_scores[str(token_order[idx])]), 4)
            for idx in topk_indices
        },
        dagger_argmax_geo_gap=max(0.0, best_geometric_score - float(geometric_scores[raw_token])),
        dagger_argmax_geo_rank=int(geometric_ranks.get(raw_token, len(evaluations) + 1)),
        veto_margin=veto_margin,
        max_geometric_rank=max_geometric_rank,
        veto_reason="actor_route_guard" if raw_idx not in safe_indices else str(base_record["veto_reason"]),
        vetoed_tokens=list(base_record["vetoed_tokens"]) + stable_vetoes,
    )
    record["axis_signals"] = _selection_axis_signals(axis_signals)
    record["hybrid_axis_scores"] = actor_axis_scores
    record["actor_route_guard_applied"] = str(token_order[chosen_idx]) != base_chosen_token
    record["actor_route_guard_previous_token"] = base_chosen_token
    record["actor_route_guard_reason"] = "prefer_route_stable_actor_safe_candidate"
    record["actor_route_guard_vetoed_tokens"] = stable_vetoes
    return record


def _select_axis_constrained(
    *,
    token_order: tuple[str, ...],
    raw_idx: int,
    topk_indices: list[int],
    policy_log_probs: np.ndarray,
    evaluations: list[Any],
    spotlight_eval_by_name: dict[str, Any],
    geometric_scores: dict[str, float],
    geometric_ranks: dict[str, int],
    best_geometric_score: float,
    spotlight_token: str,
    veto_margin: float,
    max_geometric_rank: int,
) -> dict[str, Any]:
    safe_topk_indices: list[int] = []
    vetoed_tokens: list[dict[str, Any]] = []
    raw_veto_reason = "none"

    for idx in topk_indices:
        token = str(token_order[idx])
        evaluation = spotlight_eval_by_name.get(token)
        reason = _axis_constraint_violation(token, evaluation)
        if reason is not None:
            vetoed_tokens.append({"token": token, "reason": reason})
            if idx == raw_idx:
                raw_veto_reason = reason
            continue
        safe_topk_indices.append(idx)

    used_fallback_geometric = False
    dagger_argmax_vetoed = raw_idx not in safe_topk_indices
    if safe_topk_indices:
        # Preserve the learned policy whenever independent axis constraints pass.
        chosen_idx = int(max(safe_topk_indices, key=lambda idx: float(policy_log_probs[idx])))
    else:
        feasible = [
            evaluation
            for evaluation in evaluations
            if _axis_constraint_violation(evaluation.candidate.name, evaluation) is None
        ]
        fallback_pool = feasible if feasible else evaluations
        fallback_eval = max(
            fallback_pool,
            key=lambda item: (
                item.explanation.safety_penalty <= 0.0,
                item.explanation.horizon_clearance_m,
                item.explanation.action_clearance_m,
                item.explanation.progress_bonus,
                item.explanation.effective_score,
            ),
        )
        chosen_idx = int(token_order.index(fallback_eval.candidate.name))
        used_fallback_geometric = True

    raw_token = str(token_order[raw_idx])
    return _selection_record(
        token_order=token_order,
        raw_idx=raw_idx,
        chosen_idx=chosen_idx,
        spotlight_token=spotlight_token,
        topk_indices=topk_indices,
        safe_topk_indices=safe_topk_indices,
        used_fallback_geometric=used_fallback_geometric,
        dagger_argmax_vetoed=dagger_argmax_vetoed,
        hybrid_policy_scores={str(token_order[idx]): round(float(policy_log_probs[idx]), 4) for idx in topk_indices},
        hybrid_geometric_scores={
            str(token_order[idx]): round(float(geometric_scores[str(token_order[idx])]), 4)
            for idx in topk_indices
        },
        dagger_argmax_geo_gap=max(0.0, best_geometric_score - float(geometric_scores[raw_token])),
        dagger_argmax_geo_rank=int(geometric_ranks.get(raw_token, len(evaluations) + 1)),
        veto_margin=veto_margin,
        max_geometric_rank=max_geometric_rank,
        veto_reason=raw_veto_reason,
        vetoed_tokens=vetoed_tokens,
    )


def _select_axis_lexicographic(
    *,
    token_order: tuple[str, ...],
    raw_idx: int,
    topk_indices: list[int],
    policy_log_probs: np.ndarray,
    evaluations: list[Any],
    spotlight_eval_by_name: dict[str, Any],
    geometric_scores: dict[str, float],
    geometric_ranks: dict[str, int],
    best_geometric_score: float,
    spotlight_token: str,
    veto_margin: float,
    max_geometric_rank: int,
) -> dict[str, Any]:
    safe_topk_indices: list[int] = []
    vetoed_tokens: list[dict[str, Any]] = []
    raw_veto_reason = "none"

    for idx in topk_indices:
        token = str(token_order[idx])
        evaluation = spotlight_eval_by_name.get(token)
        reason = _axis_constraint_violation(token, evaluation)
        if reason is not None:
            vetoed_tokens.append({"token": token, "reason": reason})
            if idx == raw_idx:
                raw_veto_reason = reason
            continue
        safe_topk_indices.append(idx)

    used_fallback_geometric = False
    dagger_argmax_vetoed = raw_idx not in safe_topk_indices
    if safe_topk_indices:
        chosen_idx = int(
            max(
                safe_topk_indices,
                key=lambda idx: _axis_lexicographic_key(
                    spotlight_eval_by_name[str(token_order[idx])],
                    float(policy_log_probs[idx]),
                ),
            )
        )
    else:
        feasible = [
            evaluation
            for evaluation in evaluations
            if _axis_constraint_violation(evaluation.candidate.name, evaluation) is None
        ]
        fallback_pool = feasible if feasible else evaluations
        fallback_eval = max(
            fallback_pool,
            key=lambda item: _axis_lexicographic_key(item, float("-inf")),
        )
        chosen_idx = int(token_order.index(fallback_eval.candidate.name))
        used_fallback_geometric = True

    raw_token = str(token_order[raw_idx])
    return _selection_record(
        token_order=token_order,
        raw_idx=raw_idx,
        chosen_idx=chosen_idx,
        spotlight_token=spotlight_token,
        topk_indices=topk_indices,
        safe_topk_indices=safe_topk_indices,
        used_fallback_geometric=used_fallback_geometric,
        dagger_argmax_vetoed=dagger_argmax_vetoed,
        hybrid_policy_scores={str(token_order[idx]): round(float(policy_log_probs[idx]), 4) for idx in topk_indices},
        hybrid_geometric_scores={
            str(token_order[idx]): round(float(geometric_scores[str(token_order[idx])]), 4)
            for idx in topk_indices
        },
        dagger_argmax_geo_gap=max(0.0, best_geometric_score - float(geometric_scores[raw_token])),
        dagger_argmax_geo_rank=int(geometric_ranks.get(raw_token, len(evaluations) + 1)),
        veto_margin=veto_margin,
        max_geometric_rank=max_geometric_rank,
        veto_reason=raw_veto_reason,
        vetoed_tokens=vetoed_tokens,
    )


def _axis_constraint_violation(token: str, evaluation: Any | None) -> str | None:
    if evaluation is None:
        return "missing_evaluation"
    explanation = evaluation.explanation
    if explanation.safety_penalty > 0.0:
        return "unsafe_action"
    if explanation.horizon_clearance_penalty > 0.0:
        return "horizon_clearance"
    if token == "stop" and explanation.stop_penalty > 0.0:
        return "unnecessary_stop"
    return None


def _actor_axis_route_guard_required(
    chosen_token: str,
    spotlight_eval_by_name: dict[str, Any],
    axis_signals: dict[str, dict[str, Any]],
) -> bool:
    if not any(
        _axis_signal_float(signal, "actor_count") > 0.0
        or _axis_signal_float(signal, "rear_actor_count") > 0.0
        for signal in axis_signals.values()
    ):
        return False
    if chosen_token in ROUTE_STABLE_TOKENS:
        return (
            _actor_route_stable_violation(
                chosen_token,
                spotlight_eval_by_name.get(chosen_token),
                axis_signals.get(chosen_token),
            )
            is not None
        )
    return True


def _actor_route_stable_candidates(
    *,
    token_order: tuple[str, ...],
    candidate_indices: list[int],
    spotlight_eval_by_name: dict[str, Any],
    axis_signals: dict[str, dict[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    stable_indices: list[int] = []
    vetoes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx in candidate_indices:
        if idx in seen:
            continue
        seen.add(idx)
        token = str(token_order[idx])
        reason = _actor_route_stable_violation(
            token,
            spotlight_eval_by_name.get(token),
            axis_signals.get(token),
        )
        if reason is None:
            stable_indices.append(idx)
        else:
            vetoes.append({"token": token, "reason": reason})
    return stable_indices, vetoes


def _actor_route_stable_violation(token: str, evaluation: Any | None, signal: dict[str, Any] | None) -> str | None:
    if token not in ROUTE_STABLE_TOKENS:
        return "lateral_route_risk"
    if evaluation is None:
        return "missing_evaluation"
    if signal is None:
        return "missing_axis_signal"
    explanation = evaluation.explanation
    if explanation.safety_penalty > 0.0:
        return "unsafe_action"
    if _axis_signal_float(signal, "actor_action_clearance_m") < _axis_signal_float(
        signal,
        "actor_action_clearance_min_m",
    ):
        return "actor_action_clearance"
    if _axis_signal_float(signal, "static_action_clearance_m") < _axis_signal_float(
        signal,
        "static_action_clearance_min_m",
    ):
        return "static_action_clearance"
    if (rear_reason := _actor_axis_rear_flow_violation(signal)) is not None:
        return rear_reason
    if (lane_reason := _actor_axis_lane_violation(signal)) is not None:
        return lane_reason
    if (route_reason := _actor_axis_route_violation(signal)) is not None:
        return route_reason
    return None


def _actor_axis_constraint_violation(token: str, evaluation: Any | None, signal: dict[str, Any] | None) -> str | None:
    if evaluation is None:
        return "missing_evaluation"
    if signal is None:
        return "missing_axis_signal"
    explanation = evaluation.explanation
    if _axis_signal_float(signal, "actor_action_clearance_m") < _axis_signal_float(
        signal,
        "actor_action_clearance_min_m",
    ):
        return "actor_action_clearance"
    if _axis_signal_float(signal, "actor_horizon_clearance_m") < _axis_signal_float(
        signal,
        "actor_horizon_clearance_min_m",
    ):
        return "actor_horizon_clearance"
    if _axis_signal_float(signal, "static_action_clearance_m") < _axis_signal_float(
        signal,
        "static_action_clearance_min_m",
    ):
        return "static_action_clearance"
    if (rear_reason := _actor_axis_rear_flow_violation(signal)) is not None:
        return rear_reason
    if (lane_reason := _actor_axis_lane_violation(signal)) is not None:
        return lane_reason
    if (route_reason := _actor_axis_route_violation(signal)) is not None:
        return route_reason
    if explanation.safety_penalty > 0.0:
        return "unsafe_action"
    if token == "stop" and explanation.stop_penalty > 0.0:
        return "unnecessary_stop"
    return None


def _actor_axis_lane_violation(signal: dict[str, Any]) -> str | None:
    lane_margin = _axis_signal_float(signal, "lane_margin_m")
    lane_min = _axis_signal_float(signal, "lane_margin_min_m")
    if lane_margin >= lane_min:
        return None
    start_margin = _axis_signal_float(signal, "lane_start_margin_m")
    final_margin = _axis_signal_float(signal, "lane_final_margin_m")
    if final_margin >= start_margin:
        return None
    return "lane_margin"


def _actor_axis_route_violation(signal: dict[str, Any]) -> str | None:
    route_deviation = _axis_signal_float(signal, "route_deviation_m")
    route_deviation_max = _axis_signal_float(signal, "route_deviation_max_m")
    if route_deviation <= route_deviation_max:
        return None
    start_deviation = _axis_signal_float(signal, "route_start_deviation_m")
    final_deviation = _axis_signal_float(signal, "route_final_deviation_m")
    if final_deviation <= start_deviation:
        return None
    return "route_deviation"


def _actor_axis_rear_flow_violation(signal: dict[str, Any]) -> str | None:
    if not _axis_signal_bool(signal, "rear_flow_risk"):
        return None
    return "rear_flow_risk"


def _actor_route_stable_key(evaluation: Any, signal: dict[str, Any], policy_log_prob: float) -> tuple[float, ...]:
    score = evaluation.score
    actor_action = _axis_signal_float(signal, "actor_action_clearance_m")
    actor_horizon = _axis_signal_float(signal, "actor_horizon_clearance_m")
    static_action = _axis_signal_float(signal, "static_action_clearance_m")
    static_horizon = _axis_signal_float(signal, "static_horizon_clearance_m")
    lane_margin = _axis_signal_float(signal, "lane_margin_m")
    route_deviation = _axis_signal_float(signal, "route_deviation_m")
    route_recovery = _axis_signal_float(signal, "route_recovery_m")
    rear_flow_speed = _axis_signal_float(signal, "candidate_mean_forward_speed_mps")
    rear_flow_active = _axis_signal_float(signal, "rear_closing_actor_count") > 0.0
    return (
        1.0 if score.inside_5s_region else 0.0,
        1.0 if score.inside_3s_region else 0.0,
        1.0 if _actor_axis_rear_flow_violation(signal) is None else 0.0,
        _capped_clearance(lane_margin),
        min(ACTOR_AXIS_CLEARANCE_CAP_M, rear_flow_speed) if rear_flow_active else 0.0,
        float(route_recovery),
        -float(route_deviation),
        _capped_clearance(actor_action),
        _capped_clearance(static_action),
        _capped_clearance(actor_horizon),
        _capped_clearance(static_horizon),
        float(evaluation.explanation.progress_bonus),
        float(evaluation.explanation.effective_score),
        float(policy_log_prob),
    )


def _axis_lexicographic_key(evaluation: Any, policy_log_prob: float) -> tuple[float, ...]:
    explanation = evaluation.explanation
    score = evaluation.score
    return (
        1.0 if explanation.safety_penalty <= 0.0 else 0.0,
        1.0 if explanation.horizon_clearance_penalty <= 0.0 else 0.0,
        1.0 if score.inside_5s_region else 0.0,
        1.0 if score.inside_3s_region else 0.0,
        float(explanation.horizon_clearance_m),
        float(explanation.action_clearance_m),
        float(explanation.progress_bonus),
        float(explanation.effective_score),
        float(policy_log_prob),
    )


def _actor_axis_lexicographic_key(evaluation: Any, signal: dict[str, Any], policy_log_prob: float) -> tuple[float, ...]:
    explanation = evaluation.explanation
    score = evaluation.score
    actor_action = _axis_signal_float(signal, "actor_action_clearance_m")
    actor_horizon = _axis_signal_float(signal, "actor_horizon_clearance_m")
    static_action = _axis_signal_float(signal, "static_action_clearance_m")
    static_horizon = _axis_signal_float(signal, "static_horizon_clearance_m")
    lane_margin = _axis_signal_float(signal, "lane_margin_m")
    route_deviation = _axis_signal_float(signal, "route_deviation_m")
    route_recovery = _axis_signal_float(signal, "route_recovery_m")
    rear_flow_speed = _axis_signal_float(signal, "candidate_mean_forward_speed_mps")
    rear_flow_active = _axis_signal_float(signal, "rear_closing_actor_count") > 0.0
    return (
        1.0 if _actor_axis_constraint_violation(evaluation.candidate.name, evaluation, signal) is None else 0.0,
        1.0 if actor_action >= _axis_signal_float(signal, "actor_action_clearance_min_m") else 0.0,
        1.0 if actor_horizon >= _axis_signal_float(signal, "actor_horizon_clearance_min_m") else 0.0,
        1.0 if static_action >= _axis_signal_float(signal, "static_action_clearance_min_m") else 0.0,
        1.0 if _actor_axis_rear_flow_violation(signal) is None else 0.0,
        1.0 if _actor_axis_lane_violation(signal) is None else 0.0,
        1.0 if _actor_axis_route_violation(signal) is None else 0.0,
        1.0 if score.inside_5s_region else 0.0,
        1.0 if score.inside_3s_region else 0.0,
        min(ACTOR_AXIS_CLEARANCE_CAP_M, rear_flow_speed) if rear_flow_active else 0.0,
        float(route_recovery),
        float(explanation.progress_bonus),
        float(explanation.effective_score),
        _capped_clearance(actor_action),
        _capped_clearance(actor_horizon),
        _capped_clearance(static_action),
        _capped_clearance(static_horizon),
        _capped_clearance(lane_margin),
        -float(route_deviation),
        float(policy_log_prob),
    )


def _actor_axis_score_summary(evaluation: Any, signal: dict[str, Any], policy_log_prob: float) -> dict[str, Any]:
    axis_feasible = _axis_constraint_violation(evaluation.candidate.name, evaluation) is None
    actor_proxy_feasible = _actor_axis_constraint_violation(evaluation.candidate.name, evaluation, signal) is None
    rear_flow_safe = _actor_axis_rear_flow_violation(signal) is None
    return {
        "feasible": bool(axis_feasible),
        "actor_proxy_feasible": bool(actor_proxy_feasible),
        "route_stable": bool(evaluation.candidate.name in ROUTE_STABLE_TOKENS),
        "route_stable_actor_safe": _actor_route_stable_violation(evaluation.candidate.name, evaluation, signal) is None,
        "rear_flow_safe": bool(rear_flow_safe),
        "rear_flow_risk": _axis_signal_bool(signal, "rear_flow_risk"),
        "rear_flow_ttc_s": _round_axis_value(_axis_signal_float(signal, "rear_flow_ttc_s")),
        "rear_flow_candidate_speed_mps": _round_axis_value(
            _axis_signal_float(signal, "candidate_mean_forward_speed_mps")
        ),
        "rear_flow_required_speed_mps": _round_axis_value(_axis_signal_float(signal, "rear_flow_required_speed_mps")),
        "actor_forecast_mode": str(signal.get("actor_forecast_mode", "frozen")),
        "route_source": str(signal.get("route_source", "command_proxy")),
        "route_deviation_m": _round_axis_value(_axis_signal_float(signal, "route_deviation_m")),
        "route_final_deviation_m": _round_axis_value(_axis_signal_float(signal, "route_final_deviation_m")),
        "route_recovery_m": _round_axis_value(_axis_signal_float(signal, "route_recovery_m")),
        "actor_clearance_key": _round_axis_value(_capped_clearance(_axis_signal_float(signal, "actor_action_clearance_m"))),
        "static_clearance_key": _round_axis_value(
            _capped_clearance(_axis_signal_float(signal, "static_action_clearance_m"))
        ),
        "lane_margin_key": _round_axis_value(_capped_clearance(_axis_signal_float(signal, "lane_margin_m"))),
        "progress_bonus": _round_axis_value(evaluation.explanation.progress_bonus),
        "policy_log_prob": round(float(policy_log_prob), 4) if math.isfinite(float(policy_log_prob)) else "-inf",
    }


def _axis_signal_float(signal: dict[str, Any], key: str) -> float:
    value = signal.get(key)
    if isinstance(value, str):
        if value == "inf":
            return math.inf
        if value == "-inf":
            return -math.inf
    try:
        return float(value)
    except (TypeError, ValueError):
        return -math.inf


def _axis_signal_bool(signal: dict[str, Any], key: str) -> bool:
    value = signal.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _capped_clearance(value: float) -> float:
    if math.isinf(value):
        return ACTOR_AXIS_CLEARANCE_CAP_M if value > 0.0 else -ACTOR_AXIS_CLEARANCE_CAP_M
    if math.isnan(value):
        return -ACTOR_AXIS_CLEARANCE_CAP_M
    return max(-ACTOR_AXIS_CLEARANCE_CAP_M, min(ACTOR_AXIS_CLEARANCE_CAP_M, float(value)))


def _selection_axis_signals(axis_signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        token: {key: _round_axis_value(value) for key, value in signal.items()}
        for token, signal in sorted(axis_signals.items())
    }


def _round_axis_value(value: Any) -> Any:
    if isinstance(value, bool) or isinstance(value, int):
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if math.isinf(numeric):
        return "inf" if numeric > 0.0 else "-inf"
    if math.isnan(numeric):
        return "nan"
    return round(numeric, 4)


def _selection_record(
    *,
    token_order: tuple[str, ...],
    raw_idx: int,
    chosen_idx: int,
    spotlight_token: str,
    topk_indices: list[int],
    safe_topk_indices: list[int],
    used_fallback_geometric: bool,
    dagger_argmax_vetoed: bool,
    hybrid_policy_scores: dict[str, float],
    hybrid_geometric_scores: dict[str, float],
    dagger_argmax_geo_gap: float,
    dagger_argmax_geo_rank: int,
    veto_margin: float,
    max_geometric_rank: int,
    veto_reason: str,
    vetoed_tokens: list[dict[str, Any]],
    axis_signals: dict[str, dict[str, Any]] | None = None,
    hybrid_axis_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dagger_token = str(token_order[raw_idx])
    hybrid_token = str(token_order[chosen_idx])
    if used_fallback_geometric:
        decision_type = "fallback_geometric"
    elif hybrid_token == dagger_token == spotlight_token:
        decision_type = "agreement"
    elif hybrid_token == dagger_token:
        decision_type = "dagger_wins"
    elif hybrid_token == spotlight_token:
        decision_type = "spotlight_wins"
    else:
        decision_type = "compromise"
    record = {
        "dagger_argmax_token": dagger_token,
        "spotlight_token": spotlight_token,
        "hybrid_token": hybrid_token,
        "dagger_topk_tokens": [str(token_order[idx]) for idx in topk_indices],
        "safe_topk_tokens": [str(token_order[idx]) for idx in safe_topk_indices],
        "dagger_argmax_vetoed": bool(dagger_argmax_vetoed),
        "used_fallback_geometric": bool(used_fallback_geometric),
        "hybrid_matches_dagger": hybrid_token == dagger_token,
        "hybrid_matches_spotlight": hybrid_token == spotlight_token,
        "decision_type": decision_type,
        "hybrid_policy_scores": hybrid_policy_scores,
        "hybrid_geometric_scores": hybrid_geometric_scores,
        "dagger_argmax_geo_gap": round(float(dagger_argmax_geo_gap), 4),
        "dagger_argmax_geo_rank": int(dagger_argmax_geo_rank),
        "veto_margin": round(float(veto_margin), 4),
        "max_geometric_rank": int(max_geometric_rank),
        "veto_reason": veto_reason,
        "vetoed_tokens": list(vetoed_tokens),
    }
    if axis_signals is not None:
        record["axis_signals"] = axis_signals
    if hybrid_axis_scores is not None:
        record["hybrid_axis_scores"] = hybrid_axis_scores
    return record


def _prediction_scene_id(prediction_input: Any) -> str | None:
    for field_name in ("scene_id", "clip_id", "clipgt_id"):
        value = getattr(prediction_input, field_name, None)
        if value:
            return str(value)
    metadata = getattr(prediction_input, "session_metadata", None)
    scene_id = getattr(metadata, "scene_id", None)
    if scene_id:
        return str(scene_id)
    return None


def _prediction_timestamp_us(prediction_input: Any) -> int | None:
    ego_pose_history = getattr(prediction_input, "ego_pose_history", []) or []
    for pose in reversed(list(ego_pose_history)):
        timestamp = getattr(pose, "timestamp_us", None)
        if timestamp is not None:
            return int(timestamp)

    camera_images = getattr(prediction_input, "camera_images", {}) or {}
    latest_timestamp: int | None = None
    for frames in camera_images.values():
        if not frames:
            continue
        frame = frames[-1]
        timestamp = getattr(frame, "timestamp_us", None)
        if timestamp is None and isinstance(frame, (tuple, list)) and frame:
            timestamp = frame[0]
        if timestamp is None:
            continue
        timestamp_int = int(timestamp)
        if latest_timestamp is None or timestamp_int > latest_timestamp:
            latest_timestamp = timestamp_int
    return latest_timestamp


def _prediction_ego_pose_world(prediction_input: Any) -> dict[str, float] | None:
    ego_pose_history = getattr(prediction_input, "ego_pose_history", []) or []
    for pose in reversed(list(ego_pose_history)):
        parsed = _pose_like_to_world_pose(pose)
        if parsed is not None:
            return parsed
    ego_pose = getattr(prediction_input, "ego_pose", None)
    if ego_pose is not None:
        return _pose_like_to_world_pose(ego_pose)
    return None


def _pose_like_to_world_pose(pose: Any) -> dict[str, float] | None:
    # AlpaSim passes PoseAtTime objects with the actual pose nested under
    # `.pose`; tests and some adapters may pass the pose object directly.
    raw_pose = getattr(pose, "pose", None)
    if raw_pose is not None:
        pose = raw_pose

    x = _first_float_attr(pose, ("x", "world_x"))
    y = _first_float_attr(pose, ("y", "world_y"))
    vec = getattr(pose, "vec", None)
    if x is None and vec is not None:
        x = _first_float_attr(vec, ("x",))
    if y is None and vec is not None:
        y = _first_float_attr(vec, ("y",))
    position = getattr(pose, "position", None)
    if x is None and position is not None:
        x = _first_float_attr(position, ("x",))
    if y is None and position is not None:
        y = _first_float_attr(position, ("y",))
    translation = getattr(pose, "translation", None)
    if x is None and translation is not None:
        x = _first_float_attr(translation, ("x",))
    if y is None and translation is not None:
        y = _first_float_attr(translation, ("y",))
    if x is None or y is None:
        return None

    yaw = _first_float_attr(pose, ("yaw", "heading", "heading_rad", "world_heading"))
    if yaw is None:
        quat = getattr(pose, "quat", getattr(pose, "quaternion", None))
        yaw = _yaw_from_quat_like(quat) if quat is not None else 0.0

    vx = _first_float_attr(pose, ("vx", "world_vx", "velocity_x_mps"))
    vy = _first_float_attr(pose, ("vy", "world_vy", "velocity_y_mps"))
    velocity = getattr(pose, "velocity", None)
    if vx is None and velocity is not None:
        vx = _first_float_attr(velocity, ("x", "vx"))
    if vy is None and velocity is not None:
        vy = _first_float_attr(velocity, ("y", "vy"))
    if vx is None or vy is None:
        speed = _first_float_attr(pose, ("speed", "speed_mps"))
        if speed is not None:
            vx = float(speed) * math.cos(float(yaw))
            vy = float(speed) * math.sin(float(yaw))
    return {
        "world_x": float(x),
        "world_y": float(y),
        "world_heading": float(yaw),
        "world_vx": 0.0 if vx is None else float(vx),
        "world_vy": 0.0 if vy is None else float(vy),
    }


def _load_oracle_actor_proxy(path: Path | None) -> tuple[dict[int, dict[str, Any]], list[int]]:
    if path is None:
        return {}, []
    if not path.is_file():
        raise FileNotFoundError(f"Oracle actor proxy file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid oracle actor proxy JSON: {path}") from exc
    frames_payload = payload.get("frames")
    if not isinstance(frames_payload, dict):
        raise ValueError(f"Oracle actor proxy JSON must contain a frames object: {path}")
    frames: dict[int, dict[str, Any]] = {}
    for key, frame in frames_payload.items():
        if not isinstance(frame, dict):
            continue
        timestamp = int(frame.get("timestamp_us", key))
        world_actors = frame.get("world_actors", [])
        if not isinstance(world_actors, list):
            world_actors = []
        normalized_world_actors = []
        for index, actor in enumerate(world_actors):
            normalized_actor = _normalize_oracle_world_actor(actor, index)
            if normalized_actor is not None:
                normalized_world_actors.append(normalized_actor)
        legacy_hazards = frame.get("hazards", [])
        if not isinstance(legacy_hazards, list):
            legacy_hazards = []
        normalized_legacy_hazards = []
        for index, hazard in enumerate(legacy_hazards):
            normalized = _normalize_oracle_actor_hazard(hazard, index)
            if normalized is not None:
                normalized_legacy_hazards.append(normalized)
        frames[timestamp] = {
            "timestamp_us": timestamp,
            "scene_id": frame.get("scene_id"),
            "world_actors": normalized_world_actors,
            "hazards": normalized_legacy_hazards,
        }
    return frames, sorted(frames)


def _normalize_oracle_world_actor(item: Any, index: int) -> dict[str, float | str] | None:
    if not isinstance(item, dict):
        return None
    try:
        world_x = float(item["world_x"])
        world_y = float(item["world_y"])
        radius = max(0.25, float(item.get("radius", item.get("radius_m", 1.25))))
    except (KeyError, TypeError, ValueError):
        return None
    actor: dict[str, float | str] = {
        "world_x": world_x,
        "world_y": world_y,
        "world_vx": float(item.get("world_vx", item.get("vx", 0.0))),
        "world_vy": float(item.get("world_vy", item.get("vy", 0.0))),
        "world_heading": float(item.get("world_heading", item.get("heading", 0.0))),
        "radius": radius,
        "kind": str(item.get("kind", "oracle_actor")),
        "label": str(item.get("label", item.get("id", f"oracle_actor_{index}"))),
        "source": str(item.get("source", "alpasim_oracle_actor_proxy")),
    }
    for source_key, target_key in (
        ("width", "width"),
        ("width_m", "width"),
        ("length", "length"),
        ("length_m", "length"),
        ("acceleration", "acceleration"),
        ("acceleration_mps2", "acceleration"),
        ("source_rel_x", "source_rel_x"),
        ("source_rel_y", "source_rel_y"),
    ):
        if source_key in item:
            actor[target_key] = float(item[source_key])
    if "behavior" in item:
        actor["behavior"] = str(item["behavior"])
    return actor


def _normalize_oracle_actor_hazard(item: Any, index: int) -> dict[str, float | str] | None:
    if not isinstance(item, dict):
        return None
    try:
        x = float(item["x"])
        y = float(item.get("y", 0.0))
        radius = max(0.25, float(item.get("radius", item.get("radius_m", 1.25))))
    except (KeyError, TypeError, ValueError):
        return None
    hazard: dict[str, float | str] = {
        "x": x,
        "y": y,
        "radius": radius,
        "kind": str(item.get("kind", "oracle_actor")),
        "label": str(item.get("label", item.get("id", f"oracle_actor_{index}"))),
        "vx": float(item.get("vx", item.get("forward_velocity_mps", 0.0))),
        "vy": float(item.get("vy", item.get("lateral_velocity_mps", 0.0))),
        "source": str(item.get("source", "alpasim_oracle_actor_proxy")),
    }
    for source_key, target_key in (
        ("width", "width"),
        ("width_m", "width"),
        ("length", "length"),
        ("length_m", "length"),
        ("heading", "heading"),
        ("heading_rad", "heading"),
        ("acceleration", "acceleration"),
        ("acceleration_mps2", "acceleration"),
    ):
        if source_key in item:
            hazard[target_key] = float(item[source_key])
    if "behavior" in item:
        hazard["behavior"] = str(item["behavior"])
    return hazard


def _oracle_frame_to_current_hazards(
    frame: dict[str, Any],
    prediction_input: Any,
) -> tuple[list[dict[str, float | str]] | None, dict[str, Any]]:
    world_actors = frame.get("world_actors", [])
    if world_actors:
        ego_pose = _prediction_ego_pose_world(prediction_input)
        if ego_pose is None:
            return None, {"miss_reason": "missing_current_ego_pose", "frame_space": "world"}
        speed = float(getattr(prediction_input, "speed", 0.0) or 0.0)
        ego_velocity = _current_ego_velocity_world(ego_pose, speed_mps=speed)
        hazards = [
            _world_actor_to_current_hazard(actor, ego_pose, ego_velocity, index)
            for index, actor in enumerate(world_actors)
        ]
        hazards = [hazard for hazard in hazards if hazard is not None]
        return hazards, {
            "frame_space": "world",
            "world_actor_count": len(world_actors),
            "current_ego_pose": {
                "world_x": round(float(ego_pose["world_x"]), 4),
                "world_y": round(float(ego_pose["world_y"]), 4),
                "world_heading": round(float(ego_pose["world_heading"]), 6),
            },
        }
    if frame.get("hazards"):
        return None, {
            "miss_reason": "legacy_relative_proxy_unsupported",
            "frame_space": "legacy_relative",
            "world_actor_count": 0,
            "current_ego_pose": None,
        }
    return [], {
        "frame_space": "world",
        "world_actor_count": 0,
        "current_ego_pose": None,
    }


def _current_ego_velocity_world(ego_pose: dict[str, float], *, speed_mps: float) -> tuple[float, float]:
    vx = float(ego_pose.get("world_vx", 0.0))
    vy = float(ego_pose.get("world_vy", 0.0))
    if abs(vx) > 1e-6 or abs(vy) > 1e-6:
        return vx, vy
    heading = float(ego_pose["world_heading"])
    return float(speed_mps) * math.cos(heading), float(speed_mps) * math.sin(heading)


def _world_actor_to_current_hazard(
    actor: dict[str, float | str],
    ego_pose: dict[str, float],
    ego_velocity: tuple[float, float],
    index: int,
) -> dict[str, float | str] | None:
    try:
        dx = float(actor["world_x"]) - float(ego_pose["world_x"])
        dy = float(actor["world_y"]) - float(ego_pose["world_y"])
    except (KeyError, TypeError, ValueError):
        return None
    ego_heading = float(ego_pose["world_heading"])
    forward = (math.cos(ego_heading), math.sin(ego_heading))
    left = (-math.sin(ego_heading), math.cos(ego_heading))
    rel_x = dx * forward[0] + dy * forward[1]
    rel_y = dx * left[0] + dy * left[1]
    actor_vx = float(actor.get("world_vx", 0.0))
    actor_vy = float(actor.get("world_vy", 0.0))
    rel_vx_world = actor_vx - float(ego_velocity[0])
    rel_vy_world = actor_vy - float(ego_velocity[1])
    rel_vx = rel_vx_world * forward[0] + rel_vy_world * forward[1]
    rel_vy = rel_vx_world * left[0] + rel_vy_world * left[1]
    hazard: dict[str, float | str] = {
        "x": round(rel_x, 4),
        "y": round(rel_y, 4),
        "vx": round(rel_vx, 4),
        "vy": round(rel_vy, 4),
        "radius": float(actor["radius"]),
        "kind": str(actor.get("kind", "oracle_actor")),
        "label": str(actor.get("label", f"oracle_actor_{index}")),
        "source": str(actor.get("source", "alpasim_oracle_actor_proxy")),
        "heading": round(_wrap_angle(float(actor.get("world_heading", 0.0)) - ego_heading), 6),
        "world_x": round(float(actor["world_x"]), 4),
        "world_y": round(float(actor["world_y"]), 4),
    }
    for key in ("width", "length", "behavior", "acceleration", "source_rel_x", "source_rel_y"):
        if key in actor:
            hazard[key] = actor[key]
    return hazard


def _nearest_oracle_actor_proxy_frame(
    frames: dict[int, dict[str, Any]],
    timestamps: list[int],
    requested_timestamp_us: int,
    *,
    tolerance_us: int,
) -> dict[str, Any] | None:
    if requested_timestamp_us in frames:
        return frames[requested_timestamp_us]
    if not timestamps:
        return None
    insert_at = bisect_left(timestamps, requested_timestamp_us)
    candidates: list[int] = []
    if insert_at < len(timestamps):
        candidates.append(timestamps[insert_at])
    if insert_at > 0:
        candidates.append(timestamps[insert_at - 1])
    if not candidates:
        return None
    nearest = min(candidates, key=lambda timestamp: abs(timestamp - requested_timestamp_us))
    if abs(nearest - requested_timestamp_us) > tolerance_us:
        return None
    return frames[nearest]


def _first_float_attr(obj: Any, names: tuple[str, ...]) -> float | None:
    for name in names:
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _yaw_from_quat_like(quat: Any) -> float:
    w = float(getattr(quat, "w", 1.0))
    x = float(getattr(quat, "x", 0.0))
    y = float(getattr(quat, "y", 0.0))
    z = float(getattr(quat, "z", 0.0))
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % (2.0 * math.pi) - math.pi


def _logsumexp(values: np.ndarray) -> float:
    max_value = float(np.max(values))
    return max_value + float(np.log(np.exp(values - max_value).sum()))


def _top_logits(logits: np.ndarray, token_order: tuple[str, ...], limit: int = 3) -> list[dict[str, float | str]]:
    indices = sorted(range(len(logits)), key=lambda idx: float(logits[idx]), reverse=True)[:limit]
    return [{"token": token_order[idx], "logit": round(float(logits[idx]), 4)} for idx in indices]


def _cfg_value(config: Any, key: str, default: Any) -> Any:
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)
