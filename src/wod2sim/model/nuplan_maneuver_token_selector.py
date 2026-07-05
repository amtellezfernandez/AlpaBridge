from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any
from typing import Mapping

import numpy as np

from .nuplan_maneuver_token_adapter import ManeuverTokenCandidate
from .nuplan_maneuver_token_adapter import TOKEN_ORDER
from .nuplan_maneuver_token_adapter import build_maneuver_token_candidates
from .nuplan_maneuver_token_adapter import build_scene_diagnostic_record


SELECTOR_FEATURE_NAMES = (
    "obstacle_pressure",
    "route_blockage",
    "corridor_blocked",
    "left_clearance_m",
    "right_clearance_m",
    "escape_side_float",
    "heading_error_rad",
    "lane_offset_m",
    "route_remaining_m",
    "nearest_actor_distance_m",
    "leading_actor_distance_m",
    "rear_closing_actor_count",
    "crossing_actor_count",
    "candidate_speed_scale",
    "candidate_lateral_offset_m",
    "candidate_proxy_safe",
    "candidate_min_proxy_clearance_m",
    "candidate_final_progress_m",
    "candidate_score_heuristic",
)
REPLAY_CALIBRATED_MODEL_TYPE = "nuplan_replay_calibrated_selector_v1"
REPLAY_VALUE_MODEL_TYPE = "nuplan_replay_value_selector_v1"
REPLAY_VALUE_MLP_MODEL_TYPE = "nuplan_replay_value_mlp_selector_v1"


@dataclass(frozen=True)
class NuPlanMlpSelector:
    feature_names: tuple[str, ...]
    hidden_dim: int
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    w1: tuple[tuple[float, ...], ...]
    b1: tuple[float, ...]
    w2: tuple[float, ...]
    b2: float

    def predict_score(self, features: Mapping[str, float]) -> float:
        vector = np.asarray([float(features[name]) for name in self.feature_names], dtype=np.float64)
        mean = np.asarray(self.feature_mean, dtype=np.float64)
        scale = np.asarray(self.feature_scale, dtype=np.float64)
        normalized = (vector - mean) / scale
        hidden = np.maximum(
            normalized @ np.asarray(self.w1, dtype=np.float64) + np.asarray(self.b1, dtype=np.float64),
            0.0,
        )
        return float(hidden @ np.asarray(self.w2, dtype=np.float64) + float(self.b2))

    def select_record(self, scene_record: Mapping[str, Any]) -> dict[str, Any]:
        candidates = list(scene_record["candidates"])
        scored = [
            (
                self.predict_score(selector_feature_row(scene_record, candidate)),
                candidate,
            )
            for candidate in candidates
        ]
        _, selected = max(
            scored,
            key=lambda item: (
                item[0],
                item[1]["min_proxy_clearance_m"],
                item[1]["final_progress_m"],
            ),
        )
        return dict(selected)

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_type": "nuplan_maneuvertoken_selector_mlp_v1",
            "feature_names": list(self.feature_names),
            "hidden_dim": int(self.hidden_dim),
            "feature_mean": list(self.feature_mean),
            "feature_scale": list(self.feature_scale),
            "w1": [list(row) for row in self.w1],
            "b1": list(self.b1),
            "w2": list(self.w2),
            "b2": float(self.b2),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> NuPlanMlpSelector:
        return cls(
            feature_names=tuple(str(name) for name in payload["feature_names"]),
            hidden_dim=int(payload["hidden_dim"]),
            feature_mean=tuple(float(value) for value in payload["feature_mean"]),
            feature_scale=tuple(float(value) for value in payload["feature_scale"]),
            w1=tuple(tuple(float(value) for value in row) for row in payload["w1"]),
            b1=tuple(float(value) for value in payload["b1"]),
            w2=tuple(float(value) for value in payload["w2"]),
            b2=float(payload["b2"]),
        )


@dataclass(frozen=True)
class NuPlanReplayCalibratedSelector:
    feature_names: tuple[str, ...]
    hidden_dim: int
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    w1: tuple[tuple[float, ...], ...]
    b1: tuple[float, ...]
    w2: tuple[float, ...]
    b2: float
    risk_weight: float
    proxy_score_weight: float
    progress_weight: float
    unsafe_penalty: float
    near_miss_threshold_m: float

    def predict_risk(self, features: Mapping[str, float]) -> float:
        logit = _predict_mlp_logit(
            features=features,
            feature_names=self.feature_names,
            feature_mean=self.feature_mean,
            feature_scale=self.feature_scale,
            w1=self.w1,
            b1=self.b1,
            w2=self.w2,
            b2=self.b2,
        )
        return float(1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, logit)))))

    def predict_score(self, features: Mapping[str, float]) -> float:
        risk = self.predict_risk(features)
        proxy_score = float(features["candidate_score_heuristic"])
        progress = float(features["candidate_final_progress_m"])
        proxy_safe = bool(float(features["candidate_proxy_safe"]) >= 0.5)
        unsafe_penalty = 0.0 if proxy_safe else float(self.unsafe_penalty)
        return (
            float(self.proxy_score_weight) * proxy_score
            + float(self.progress_weight) * progress
            - float(self.risk_weight) * risk
            - unsafe_penalty
        )

    def select_record(self, scene_record: Mapping[str, Any]) -> dict[str, Any]:
        candidates = list(scene_record["candidates"])
        scored = [
            (
                self.predict_score(selector_feature_row(scene_record, candidate)),
                candidate,
            )
            for candidate in candidates
        ]
        _, selected = max(
            scored,
            key=lambda item: (
                item[0],
                item[1]["min_proxy_clearance_m"],
                item[1]["final_progress_m"],
            ),
        )
        return dict(selected)

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_type": REPLAY_CALIBRATED_MODEL_TYPE,
            "feature_names": list(self.feature_names),
            "hidden_dim": int(self.hidden_dim),
            "feature_mean": list(self.feature_mean),
            "feature_scale": list(self.feature_scale),
            "w1": [list(row) for row in self.w1],
            "b1": list(self.b1),
            "w2": list(self.w2),
            "b2": float(self.b2),
            "risk_weight": float(self.risk_weight),
            "proxy_score_weight": float(self.proxy_score_weight),
            "progress_weight": float(self.progress_weight),
            "unsafe_penalty": float(self.unsafe_penalty),
            "near_miss_threshold_m": float(self.near_miss_threshold_m),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> NuPlanReplayCalibratedSelector:
        return cls(
            feature_names=tuple(str(name) for name in payload["feature_names"]),
            hidden_dim=int(payload["hidden_dim"]),
            feature_mean=tuple(float(value) for value in payload["feature_mean"]),
            feature_scale=tuple(float(value) for value in payload["feature_scale"]),
            w1=tuple(tuple(float(value) for value in row) for row in payload["w1"]),
            b1=tuple(float(value) for value in payload["b1"]),
            w2=tuple(float(value) for value in payload["w2"]),
            b2=float(payload["b2"]),
            risk_weight=float(payload.get("risk_weight", 4.0)),
            proxy_score_weight=float(payload.get("proxy_score_weight", 1.0)),
            progress_weight=float(payload.get("progress_weight", 0.0)),
            unsafe_penalty=float(payload.get("unsafe_penalty", 2.0)),
            near_miss_threshold_m=float(payload.get("near_miss_threshold_m", 1.0)),
        )


@dataclass(frozen=True)
class NuPlanReplayValueSelector:
    feature_names: tuple[str, ...]
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float

    def predict_score(self, features: Mapping[str, float]) -> float:
        vector = np.asarray([float(features[name]) for name in self.feature_names], dtype=np.float64)
        mean = np.asarray(self.feature_mean, dtype=np.float64)
        scale = np.asarray(self.feature_scale, dtype=np.float64)
        normalized = (vector - mean) / scale
        return float(normalized @ np.asarray(self.weights, dtype=np.float64) + float(self.bias))

    def select_record(self, scene_record: Mapping[str, Any]) -> dict[str, Any]:
        candidates = list(scene_record["candidates"])
        scored = [
            (
                self.predict_score(selector_feature_row(scene_record, candidate)),
                candidate,
            )
            for candidate in candidates
        ]
        _, selected = max(
            scored,
            key=lambda item: (
                item[0],
                item[1]["min_proxy_clearance_m"],
                item[1]["final_progress_m"],
            ),
        )
        return dict(selected)

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_type": REPLAY_VALUE_MODEL_TYPE,
            "feature_names": list(self.feature_names),
            "feature_mean": list(self.feature_mean),
            "feature_scale": list(self.feature_scale),
            "weights": list(self.weights),
            "bias": float(self.bias),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "NuPlanReplayValueSelector":
        return cls(
            feature_names=tuple(str(name) for name in payload["feature_names"]),
            feature_mean=tuple(float(value) for value in payload["feature_mean"]),
            feature_scale=tuple(float(value) for value in payload["feature_scale"]),
            weights=tuple(float(value) for value in payload["weights"]),
            bias=float(payload["bias"]),
        )


@dataclass(frozen=True)
class NuPlanReplayValueMlpSelector:
    feature_names: tuple[str, ...]
    hidden_dim: int
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    target_mean: float
    target_scale: float
    w1: tuple[tuple[float, ...], ...]
    b1: tuple[float, ...]
    w2: tuple[float, ...]
    b2: float

    def predict_score(self, features: Mapping[str, float]) -> float:
        normalized_value = _predict_mlp_logit(
            features=features,
            feature_names=self.feature_names,
            feature_mean=self.feature_mean,
            feature_scale=self.feature_scale,
            w1=self.w1,
            b1=self.b1,
            w2=self.w2,
            b2=self.b2,
        )
        return float(float(self.target_mean) + float(self.target_scale) * normalized_value)

    def select_record(self, scene_record: Mapping[str, Any]) -> dict[str, Any]:
        candidates = list(scene_record["candidates"])
        scored = [
            (
                self.predict_score(selector_feature_row(scene_record, candidate)),
                candidate,
            )
            for candidate in candidates
        ]
        _, selected = max(
            scored,
            key=lambda item: (
                item[0],
                item[1]["min_proxy_clearance_m"],
                item[1]["final_progress_m"],
            ),
        )
        return dict(selected)

    def to_payload(self) -> dict[str, Any]:
        return {
            "model_type": REPLAY_VALUE_MLP_MODEL_TYPE,
            "feature_names": list(self.feature_names),
            "hidden_dim": int(self.hidden_dim),
            "feature_mean": list(self.feature_mean),
            "feature_scale": list(self.feature_scale),
            "target_mean": float(self.target_mean),
            "target_scale": float(self.target_scale),
            "w1": [list(row) for row in self.w1],
            "b1": list(self.b1),
            "w2": list(self.w2),
            "b2": float(self.b2),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "NuPlanReplayValueMlpSelector":
        return cls(
            feature_names=tuple(str(name) for name in payload["feature_names"]),
            hidden_dim=int(payload["hidden_dim"]),
            feature_mean=tuple(float(value) for value in payload["feature_mean"]),
            feature_scale=tuple(float(value) for value in payload["feature_scale"]),
            target_mean=float(payload.get("target_mean", 0.0)),
            target_scale=float(payload.get("target_scale", 1.0)),
            w1=tuple(tuple(float(value) for value in row) for row in payload["w1"]),
            b1=tuple(float(value) for value in payload["b1"]),
            w2=tuple(float(value) for value in payload["w2"]),
            b2=float(payload["b2"]),
        )


def selector_from_payload(
    payload: Mapping[str, Any],
) -> NuPlanMlpSelector | NuPlanReplayCalibratedSelector | NuPlanReplayValueSelector | NuPlanReplayValueMlpSelector:
    model_type = str(payload.get("model_type", "nuplan_maneuvertoken_selector_mlp_v1"))
    if model_type == REPLAY_CALIBRATED_MODEL_TYPE:
        return NuPlanReplayCalibratedSelector.from_payload(payload)
    if model_type == REPLAY_VALUE_MODEL_TYPE:
        return NuPlanReplayValueSelector.from_payload(payload)
    if model_type == REPLAY_VALUE_MLP_MODEL_TYPE:
        return NuPlanReplayValueMlpSelector.from_payload(payload)
    return NuPlanMlpSelector.from_payload(payload)


def load_selector(
    path: Path,
) -> NuPlanMlpSelector | NuPlanReplayCalibratedSelector | NuPlanReplayValueSelector | NuPlanReplayValueMlpSelector:
    return selector_from_payload(json.loads(path.read_text(encoding="utf-8")))


def selector_feature_row(scene_record: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, float]:
    six_scalar_state = scene_record["six_scalar_state"]
    route = scene_record["route_features"]
    actor_summary = scene_record["actor_summary"]
    return {
        "obstacle_pressure": float(six_scalar_state["obstacle_pressure"]),
        "route_blockage": float(six_scalar_state["route_blockage"]),
        "corridor_blocked": 1.0 if bool(six_scalar_state["corridor_blocked"]) else 0.0,
        "left_clearance_m": float(six_scalar_state["left_clearance_m"]),
        "right_clearance_m": float(six_scalar_state["right_clearance_m"]),
        "escape_side_float": float(six_scalar_state["vector"][5]),
        "heading_error_rad": float(route["heading_error_rad"]),
        "lane_offset_m": float(route["lane_offset_m"]),
        "route_remaining_m": float(route["route_remaining_m"]),
        "nearest_actor_distance_m": float(actor_summary["nearest_actor_distance_m"]),
        "leading_actor_distance_m": float(actor_summary["leading_actor_distance_m"]),
        "rear_closing_actor_count": float(actor_summary["rear_closing_actor_count"]),
        "crossing_actor_count": float(actor_summary["crossing_actor_count"]),
        "candidate_speed_scale": float(candidate["speed_scale"]),
        "candidate_lateral_offset_m": float(candidate["lateral_offset_m"]),
        "candidate_proxy_safe": 1.0 if bool(candidate["proxy_safe"]) else 0.0,
        "candidate_min_proxy_clearance_m": float(candidate["min_proxy_clearance_m"]),
        "candidate_final_progress_m": float(candidate["final_progress_m"]),
        "candidate_score_heuristic": float(candidate["score"]),
    }


def build_training_examples(scenes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    examples = []
    for scene in scenes:
        scene_record = build_scene_diagnostic_record(scene)
        expert_trajectory = list(scene.get("expert_trajectory", []))
        if not expert_trajectory:
            raise ValueError(f"scene {scene_record['scene_id']!r} is missing expert_trajectory")
        best_token = best_supervision_token(scene)
        for candidate in scene_record["candidates"]:
            examples.append(
                {
                    "scene_id": scene_record["scene_id"],
                    "token": candidate["token"],
                    "label": 1.0 if candidate["token"] == best_token else 0.0,
                    "supervision_score": supervision_score(scene_record, candidate, expert_trajectory),
                    "features": selector_feature_row(scene_record, candidate),
                }
            )
    return examples


def best_supervision_token(scene: Mapping[str, Any]) -> str:
    scene_record = build_scene_diagnostic_record(scene)
    expert_trajectory = list(scene.get("expert_trajectory", []))
    if not expert_trajectory:
        raise ValueError(f"scene {scene_record['scene_id']!r} is missing expert_trajectory")
    scored = [
        (
            supervision_score(scene_record, candidate, expert_trajectory),
            candidate["token"],
        )
        for candidate in scene_record["candidates"]
    ]
    return max(scored, key=lambda item: (item[0], -TOKEN_ORDER.index(item[1])))[1]


def supervision_score(
    scene_record: Mapping[str, Any],
    candidate: Mapping[str, Any],
    expert_trajectory: list[Mapping[str, Any] | list[float] | tuple[float, ...]],
) -> float:
    imitation = imitation_distance(candidate["poses"], expert_trajectory)
    proxy_safe_bonus = 2.5 if bool(candidate["proxy_safe"]) else -2.5
    clearance_bonus = min(2.0, float(candidate["min_proxy_clearance_m"]) / 2.0)
    route_penalty = abs(float(scene_record["route_features"]["lane_offset_m"])) * 0.15
    return -imitation + proxy_safe_bonus + clearance_bonus - route_penalty


def imitation_distance(
    candidate_poses: list[list[float] | tuple[float, ...]],
    expert_trajectory: list[Mapping[str, Any] | list[float] | tuple[float, ...]],
) -> float:
    count = min(len(candidate_poses), len(expert_trajectory))
    if count <= 0:
        return float("inf")
    total = 0.0
    for index in range(count):
        candidate = candidate_poses[index]
        expert = expert_trajectory[index]
        cx = float(candidate[0])
        cy = float(candidate[1])
        ex = float(expert["x_m"]) if isinstance(expert, Mapping) else float(expert[0])
        ey = float(expert["y_m"]) if isinstance(expert, Mapping) else float(expert[1])
        total += math.hypot(cx - ex, cy - ey)
    return total / count


def fit_selector_mlp(
    examples: list[Mapping[str, Any]],
    *,
    hidden_dim: int = 16,
    epochs: int = 250,
    learning_rate: float = 0.05,
    seed: int = 0,
) -> tuple[NuPlanMlpSelector, dict[str, float]]:
    if not examples:
        raise ValueError("cannot train selector on an empty example set")
    feature_names = tuple(SELECTOR_FEATURE_NAMES)
    fitted = _fit_binary_mlp(
        examples=examples,
        label_key="label",
        feature_names=feature_names,
        hidden_dim=hidden_dim,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
    )
    selector = NuPlanMlpSelector(
        feature_names=feature_names,
        hidden_dim=int(hidden_dim),
        feature_mean=fitted["feature_mean"],
        feature_scale=fitted["feature_scale"],
        w1=fitted["w1"],
        b1=fitted["b1"],
        w2=fitted["w2"],
        b2=fitted["b2"],
    )
    metrics = evaluate_selector(selector, examples)
    return selector, metrics


def build_replay_calibration_examples(
    replay_report: Mapping[str, Any],
    *,
    near_miss_threshold_m: float = 1.0,
) -> list[dict[str, Any]]:
    examples = []
    for scene in replay_report.get("scenes", []):
        candidate_by_token = {str(candidate["token"]): candidate for candidate in scene.get("candidates", [])}
        replay_by_token = {
            str(candidate["token"]): candidate for candidate in scene.get("candidate_replay_evaluations", [])
        }
        for token, candidate in candidate_by_token.items():
            replay = replay_by_token.get(token)
            if replay is None or replay.get("realized_min_clearance_m") is None:
                continue
            realized_clearance = float(replay["realized_min_clearance_m"])
            examples.append(
                {
                    "scene_id": str(scene["scene_id"]),
                    "source_db_file": str(scene.get("source_db_file", "")),
                    "token": token,
                    "replay_infeasible": 1.0 if realized_clearance < near_miss_threshold_m else 0.0,
                    "replay_min_clearance_m": realized_clearance,
                    "proxy_safe": bool(candidate.get("proxy_safe")),
                    "proxy_score": float(candidate.get("score", 0.0)),
                    "final_progress_m": float(candidate.get("final_progress_m", 0.0)),
                    "features": selector_feature_row(scene, candidate),
                }
            )
    return examples


def fit_replay_calibrated_selector(
    examples: list[Mapping[str, Any]],
    *,
    hidden_dim: int = 16,
    epochs: int = 250,
    learning_rate: float = 0.05,
    seed: int = 0,
    risk_weight: float = 4.0,
    proxy_score_weight: float = 1.0,
    progress_weight: float = 0.0,
    unsafe_penalty: float = 2.0,
    near_miss_threshold_m: float = 1.0,
) -> tuple[NuPlanReplayCalibratedSelector, dict[str, float]]:
    if not examples:
        raise ValueError("cannot train replay-calibrated selector on an empty example set")
    feature_names = tuple(SELECTOR_FEATURE_NAMES)
    fitted = _fit_binary_mlp(
        examples=examples,
        label_key="replay_infeasible",
        feature_names=feature_names,
        hidden_dim=hidden_dim,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
    )
    selector = NuPlanReplayCalibratedSelector(
        feature_names=feature_names,
        hidden_dim=int(hidden_dim),
        feature_mean=fitted["feature_mean"],
        feature_scale=fitted["feature_scale"],
        w1=fitted["w1"],
        b1=fitted["b1"],
        w2=fitted["w2"],
        b2=fitted["b2"],
        risk_weight=float(risk_weight),
        proxy_score_weight=float(proxy_score_weight),
        progress_weight=float(progress_weight),
        unsafe_penalty=float(unsafe_penalty),
        near_miss_threshold_m=float(near_miss_threshold_m),
    )
    return selector, evaluate_replay_risk_head(selector, examples)


def fit_replay_value_selector(
    examples: list[Mapping[str, Any]],
    *,
    ridge_alpha: float = 1.0e-3,
) -> tuple[NuPlanReplayValueSelector, dict[str, float]]:
    if not examples:
        raise ValueError("cannot train replay-value selector on an empty example set")
    feature_names = tuple(SELECTOR_FEATURE_NAMES)
    x = np.asarray(
        [[float(example["features"][name]) for name in feature_names] for example in examples],
        dtype=np.float64,
    )
    y = np.asarray([float(example["objective_value"]) for example in examples], dtype=np.float64)
    weights = np.asarray([float(example.get("example_weight", 1.0)) for example in examples], dtype=np.float64)
    weights = np.clip(weights, 1.0e-6, None)
    feature_mean = x.mean(axis=0)
    feature_scale = x.std(axis=0)
    feature_scale[feature_scale < 1.0e-8] = 1.0
    x_norm = (x - feature_mean) / feature_scale
    design = np.concatenate([x_norm, np.ones((x_norm.shape[0], 1), dtype=np.float64)], axis=1)
    penalty = np.eye(design.shape[1], dtype=np.float64) * float(ridge_alpha)
    penalty[-1, -1] = 0.0
    weighted_design = design * weights[:, None]
    coefficients = np.linalg.solve(design.T @ weighted_design + penalty, design.T @ (weights * y))
    predictions = design @ coefficients
    selector = NuPlanReplayValueSelector(
        feature_names=feature_names,
        feature_mean=tuple(float(value) for value in feature_mean),
        feature_scale=tuple(float(value) for value in feature_scale),
        weights=tuple(float(value) for value in coefficients[:-1]),
        bias=float(coefficients[-1]),
    )
    metrics = {
        "example_count": float(len(examples)),
        "mean_example_weight": float(weights.mean()),
        "objective_mean": float(y.mean()),
        "objective_mse": float(np.mean((predictions - y) ** 2)),
        "objective_mae": float(np.mean(np.abs(predictions - y))),
    }
    return selector, metrics


def fit_replay_value_mlp_selector(
    examples: list[Mapping[str, Any]],
    *,
    hidden_dim: int = 32,
    epochs: int = 400,
    learning_rate: float = 0.03,
    seed: int = 0,
    feature_names: tuple[str, ...] | None = None,
) -> tuple[NuPlanReplayValueMlpSelector, dict[str, float]]:
    if not examples:
        raise ValueError("cannot train replay-value MLP selector on an empty example set")
    feature_names = tuple(SELECTOR_FEATURE_NAMES if feature_names is None else feature_names)
    fitted = _fit_regression_mlp(
        examples=examples,
        target_key="objective_value",
        feature_names=feature_names,
        hidden_dim=hidden_dim,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
    )
    selector = NuPlanReplayValueMlpSelector(
        feature_names=feature_names,
        hidden_dim=int(hidden_dim),
        feature_mean=fitted["feature_mean"],
        feature_scale=fitted["feature_scale"],
        target_mean=float(fitted["target_mean"]),
        target_scale=float(fitted["target_scale"]),
        w1=fitted["w1"],
        b1=fitted["b1"],
        w2=fitted["w2"],
        b2=fitted["b2"],
    )
    predictions = np.asarray(
        [selector.predict_score(example["features"]) for example in examples],
        dtype=np.float64,
    )
    targets = np.asarray([float(example["objective_value"]) for example in examples], dtype=np.float64)
    weights = np.asarray([float(example.get("example_weight", 1.0)) for example in examples], dtype=np.float64)
    return selector, {
        "example_count": float(len(examples)),
        "mean_example_weight": float(weights.mean()),
        "objective_mean": float(targets.mean()),
        "objective_mse": float(np.mean((predictions - targets) ** 2)),
        "objective_mae": float(np.mean(np.abs(predictions - targets))),
        "target_mean": float(fitted["target_mean"]),
        "target_scale": float(fitted["target_scale"]),
    }


def evaluate_replay_risk_head(
    selector: NuPlanReplayCalibratedSelector,
    examples: list[Mapping[str, Any]],
) -> dict[str, float]:
    if not examples:
        return {"example_count": 0.0, "risk_accuracy": 0.0, "risk_log_loss": 0.0}
    labels = np.asarray([float(example["replay_infeasible"]) for example in examples], dtype=np.float64)
    probs = np.asarray([selector.predict_risk(example["features"]) for example in examples], dtype=np.float64)
    predictions = probs >= 0.5
    loss = -np.mean(
        labels * np.log(np.clip(probs, 1.0e-8, 1.0))
        + (1.0 - labels) * np.log(np.clip(1.0 - probs, 1.0e-8, 1.0))
    )
    return {
        "example_count": float(len(examples)),
        "risk_positive_rate": float(labels.mean()),
        "risk_accuracy": float(np.mean(predictions == (labels >= 0.5))),
        "risk_log_loss": float(loss),
    }


def _fit_binary_mlp(
    *,
    examples: list[Mapping[str, Any]],
    label_key: str,
    feature_names: tuple[str, ...],
    hidden_dim: int,
    epochs: int,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    x = np.asarray(
        [[float(example["features"][name]) for name in feature_names] for example in examples],
        dtype=np.float64,
    )
    y = np.asarray([float(example[label_key]) for example in examples], dtype=np.float64).reshape(-1, 1)
    weights = np.asarray([float(example.get("example_weight", 1.0)) for example in examples], dtype=np.float64)
    weights = np.clip(weights, 1.0e-6, None).reshape(-1, 1)
    weights = weights / float(weights.mean())
    feature_mean = x.mean(axis=0)
    feature_scale = x.std(axis=0)
    feature_scale[feature_scale < 1.0e-8] = 1.0
    x_norm = (x - feature_mean) / feature_scale
    rng = np.random.default_rng(seed)
    w1 = rng.normal(0.0, 0.15, size=(x_norm.shape[1], hidden_dim))
    b1 = np.zeros((hidden_dim,), dtype=np.float64)
    w2 = rng.normal(0.0, 0.15, size=(hidden_dim, 1))
    b2 = np.zeros((1,), dtype=np.float64)
    for _ in range(max(1, epochs)):
        z1 = x_norm @ w1 + b1
        h1 = np.maximum(z1, 0.0)
        logits = h1 @ w2 + b2
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
        grad_logits = (weights * (probs - y)) / x_norm.shape[0]
        grad_w2 = h1.T @ grad_logits
        grad_b2 = grad_logits.sum(axis=0)
        grad_h1 = grad_logits @ w2.T
        grad_z1 = grad_h1 * (z1 > 0.0)
        grad_w1 = x_norm.T @ grad_z1
        grad_b1 = grad_z1.sum(axis=0)
        w1 -= learning_rate * grad_w1
        b1 -= learning_rate * grad_b1
        w2 -= learning_rate * grad_w2
        b2 -= learning_rate * grad_b2
    return {
        "feature_mean": tuple(float(value) for value in feature_mean),
        "feature_scale": tuple(float(value) for value in feature_scale),
        "w1": tuple(tuple(float(value) for value in row) for row in w1),
        "b1": tuple(float(value) for value in b1),
        "w2": tuple(float(value) for value in w2[:, 0]),
        "b2": float(b2[0]),
    }


def _fit_regression_mlp(
    *,
    examples: list[Mapping[str, Any]],
    target_key: str,
    feature_names: tuple[str, ...],
    hidden_dim: int,
    epochs: int,
    learning_rate: float,
    seed: int,
) -> dict[str, Any]:
    x = np.asarray(
        [[float(example["features"][name]) for name in feature_names] for example in examples],
        dtype=np.float64,
    )
    y_raw = np.asarray([float(example[target_key]) for example in examples], dtype=np.float64).reshape(-1, 1)
    weights = np.asarray([float(example.get("example_weight", 1.0)) for example in examples], dtype=np.float64)
    weights = np.clip(weights, 1.0e-6, None).reshape(-1, 1)
    weights = weights / float(weights.mean())
    feature_mean = x.mean(axis=0)
    feature_scale = x.std(axis=0)
    feature_scale[feature_scale < 1.0e-8] = 1.0
    target_mean = float(y_raw.mean())
    target_scale = float(y_raw.std())
    if target_scale < 1.0e-8:
        target_scale = 1.0
    x_norm = (x - feature_mean) / feature_scale
    y = (y_raw - target_mean) / target_scale
    rng = np.random.default_rng(seed)
    w1 = rng.normal(0.0, 0.12, size=(x_norm.shape[1], hidden_dim))
    b1 = np.zeros((hidden_dim,), dtype=np.float64)
    w2 = rng.normal(0.0, 0.12, size=(hidden_dim, 1))
    b2 = np.zeros((1,), dtype=np.float64)
    for _ in range(max(1, epochs)):
        z1 = x_norm @ w1 + b1
        h1 = np.maximum(z1, 0.0)
        predictions = h1 @ w2 + b2
        grad_predictions = weights * (predictions - y) / x_norm.shape[0]
        grad_w2 = h1.T @ grad_predictions
        grad_b2 = grad_predictions.sum(axis=0)
        grad_h1 = grad_predictions @ w2.T
        grad_z1 = grad_h1 * (z1 > 0.0)
        grad_w1 = x_norm.T @ grad_z1
        grad_b1 = grad_z1.sum(axis=0)
        w1 -= learning_rate * grad_w1
        b1 -= learning_rate * grad_b1
        w2 -= learning_rate * grad_w2
        b2 -= learning_rate * grad_b2
    return {
        "feature_mean": tuple(float(value) for value in feature_mean),
        "feature_scale": tuple(float(value) for value in feature_scale),
        "target_mean": float(target_mean),
        "target_scale": float(target_scale),
        "w1": tuple(tuple(float(value) for value in row) for row in w1),
        "b1": tuple(float(value) for value in b1),
        "w2": tuple(float(value) for value in w2[:, 0]),
        "b2": float(b2[0]),
    }


def _predict_mlp_logit(
    *,
    features: Mapping[str, float],
    feature_names: tuple[str, ...],
    feature_mean: tuple[float, ...],
    feature_scale: tuple[float, ...],
    w1: tuple[tuple[float, ...], ...],
    b1: tuple[float, ...],
    w2: tuple[float, ...],
    b2: float,
) -> float:
    vector = np.asarray([float(features[name]) for name in feature_names], dtype=np.float64)
    mean = np.asarray(feature_mean, dtype=np.float64)
    scale = np.asarray(feature_scale, dtype=np.float64)
    normalized = (vector - mean) / scale
    hidden = np.maximum(
        normalized @ np.asarray(w1, dtype=np.float64) + np.asarray(b1, dtype=np.float64),
        0.0,
    )
    return float(hidden @ np.asarray(w2, dtype=np.float64) + float(b2))


def evaluate_selector(
    selector: NuPlanMlpSelector,
    examples: list[Mapping[str, Any]],
) -> dict[str, float]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for example in examples:
        grouped.setdefault(str(example["scene_id"]), []).append(example)
    correct = 0
    for rows in grouped.values():
        predicted = max(
            rows,
            key=lambda row: (
                selector.predict_score(row["features"]),
                float(row["supervision_score"]),
            ),
        )
        target = max(
            rows,
            key=lambda row: (float(row["label"]), float(row["supervision_score"])),
        )
        if str(predicted["token"]) == str(target["token"]):
            correct += 1
    logits = np.asarray(
        [selector.predict_score(row["features"]) for row in examples],
        dtype=np.float64,
    )
    labels = np.asarray([float(row["label"]) for row in examples], dtype=np.float64)
    probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
    loss = -np.mean(
        labels * np.log(np.clip(probs, 1.0e-8, 1.0))
        + (1.0 - labels) * np.log(np.clip(1.0 - probs, 1.0e-8, 1.0))
    )
    return {
        "scene_accuracy": correct / max(1, len(grouped)),
        "example_log_loss": float(loss),
        "scene_count": float(len(grouped)),
        "example_count": float(len(examples)),
    }


def select_with_model(
    selector: NuPlanMlpSelector,
    scene: Mapping[str, Any],
) -> tuple[ManeuverTokenCandidate, float]:
    candidates = build_maneuver_token_candidates(scene)
    scene_record = build_scene_diagnostic_record(scene)
    best_candidate = None
    best_score = float("-inf")
    for candidate, candidate_record in zip(candidates, scene_record["candidates"]):
        score = selector.predict_score(selector_feature_row(scene_record, candidate_record))
        if best_candidate is None or (score, candidate.min_proxy_clearance_m, candidate.final_progress_m) > (
            best_score,
            best_candidate.min_proxy_clearance_m,
            best_candidate.final_progress_m,
        ):
            best_candidate = candidate
            best_score = score
    if best_candidate is None:
        raise AssertionError("selector saw no candidates")
    return best_candidate, float(best_score)
