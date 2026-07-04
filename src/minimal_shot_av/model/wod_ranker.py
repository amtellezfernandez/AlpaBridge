from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame
from .wod_preference import trajectory_features


DEFAULT_NUMERIC_FEATURES = [
    "intent",
    "init_speed_mps",
    "endpoint_distance",
    "total_distance",
    "mean_step_distance",
    "max_step_distance",
    "min_step_distance",
    "final_lateral_abs",
    "max_lateral_abs",
    "lateral_range",
    "forward_progress",
    "mean_speed_mps",
    "max_speed_mps",
    "final_speed_mps",
    "mean_abs_accel_mps2",
    "max_abs_accel_mps2",
    "mean_abs_lateral_step",
    "max_abs_lateral_step",
    "signed_lateral_5s",
    "intent_turn_alignment",
    "mean_abs_heading_change",
    "max_abs_heading_change",
    "x_1s",
    "y_1s",
    "x_2s",
    "y_2s",
    "x_3s",
    "y_3s",
    "x_4s",
    "y_4s",
    "x_5s",
    "y_5s",
]
SOURCE_FEATURES = [
    "source_kinematic",
    "source_learned",
    "source_scene",
    "source_temporal",
    "source_anchor",
    "source_world",
    "source_internnav",
    "source_internvla",
    "source_system2",
]
CONTEXT_FEATURES = [
    "speed_bin_stopped_or_creep",
    "speed_bin_slow",
    "speed_bin_urban",
    "speed_bin_fast",
    "intent_1",
    "intent_2",
    "intent_3",
]
INTENT_FEATURES = ["intent_1", "intent_2", "intent_3"]
INTENT_INTERACTION_FEATURES = [
    f"{source}_x_{context}"
    for source in SOURCE_FEATURES
    for context in INTENT_FEATURES
]
CONTEXT_INTERACTION_FEATURES = [
    f"{source}_x_{context}"
    for source in SOURCE_FEATURES
    for context in CONTEXT_FEATURES
]
WORLD_CANDIDATE_FEATURES = [
    "world_nearest_distance",
    "world_nearest_distance_log",
    "world_neighbor_count",
    "source_world_x_world_nearest_distance_log",
]
CANDIDATE_MODEL_FEATURES = [
    "candidate_model_confidence",
    "candidate_model_confidence_signed_log",
    "candidate_model_confidence_abs_log",
    "candidate_model_confidence_present",
]
RETRIEVAL_LATENT_DISAGREEMENT_FEATURES = [
    "retrieval_support_score",
    "latent_feasibility_score",
    "retrieval_latent_disagreement",
    "retrieval_latent_abs_disagreement",
    "retrieval_latent_agreement",
    "retrieval_without_latent",
    "latent_without_retrieval",
    "retrieval_latent_low_support",
]
WORLD_PRIOR_FEATURES = [
    "world_prior_latent_error",
    "world_prior_latent_error_log",
    "world_prior_latent_error_z",
    "world_prior_progress_error",
    "world_prior_lateral_error",
    "world_prior_speed_error",
    "world_prior_heading_error",
    "world_prior_constraint_cost",
    "world_prior_predicted_final_x",
    "world_prior_predicted_final_y",
]
GEOMETRY_PRIOR_FEATURES = [
    "signed_lateral_3s",
    "turn_lateral_alignment_3s",
    "turn_lateral_alignment_5s",
    "expected_progress_5s",
    "progress_ratio_5s",
    "progress_error_5s",
    "progress_error_abs_5s",
    "stop_distance_error",
    "reverse_distance",
    "monotonic_forward_rate",
    "lateral_to_progress_ratio",
    "curvature_per_meter",
    "final_speed_ratio",
]
FRAME_RELATIVE_FEATURES = [
    "endpoint_distance_frame_z",
    "endpoint_distance_frame_rank",
    "total_distance_frame_z",
    "total_distance_frame_rank",
    "forward_progress_frame_z",
    "forward_progress_frame_rank",
    "final_lateral_abs_frame_z",
    "final_lateral_abs_frame_rank",
    "signed_lateral_5s_frame_z",
    "mean_abs_heading_change_frame_z",
    "max_abs_accel_mps2_frame_z",
    "progress_error_abs_5s_frame_z",
    "lateral_to_progress_ratio_frame_z",
    "curvature_per_meter_frame_z",
    "waypoint_mean_l2_to_frame_median",
    "waypoint_final_l2_to_frame_median",
    "waypoint_mean_l2_to_frame_mean",
    "waypoint_nearest_neighbor_l2",
    "waypoint_outlier_ratio",
    "candidate_count_log",
    "candidate_index_fraction",
]
FAMILY_RELIABILITY_FEATURES = [
    "family_reliability_mean_rfs",
    "family_reliability_oracle_rate",
    "family_reliability_regret_mean",
    "family_reliability_count_log",
    "source_reliability_mean_rfs",
    "source_reliability_oracle_rate",
    "source_reliability_regret_mean",
    "source_reliability_count_log",
]
LEARNED_RELIABILITY_FEATURES = [
    "learned_reliability_mean_rfs",
    "learned_reliability_oracle_score",
    "learned_reliability_regret",
    "learned_reliability_margin",
    "learned_reliability_frame_delta_score",
    "learned_reliability_frame_rank_score",
    "learned_reliability_rfs_frame_delta",
    "learned_reliability_oracle_frame_delta",
    "learned_reliability_regret_frame_delta",
    "learned_reliability_frame_delta_centered",
    "learned_reliability_rfs_frame_rank",
    "learned_reliability_oracle_frame_rank",
    "learned_reliability_regret_frame_rank",
    "learned_reliability_frame_delta_rank",
]
EXTERNAL_EMBEDDING_FEATURES = [f"external_embedding_{index:02d}" for index in range(64)]
EXTERNAL_EMBEDDING_SOURCE_INTERACTION_FEATURES = [
    f"{source}_x_{feature}"
    for source in SOURCE_FEATURES
    for feature in EXTERNAL_EMBEDDING_FEATURES
]
CAMERA_NAMES = ["FRONT", "FRONT_LEFT", "FRONT_RIGHT", "SIDE_LEFT", "SIDE_RIGHT", "REAR_LEFT", "REAR", "REAR_RIGHT"]
CAMERA_PAYLOAD_FEATURES = [
    "camera_count",
    "camera_payload_bytes_total_log",
    "camera_payload_bytes_mean_log",
    *[f"camera_{name.lower()}_present" for name in CAMERA_NAMES],
    *[f"camera_{name.lower()}_bytes_log" for name in CAMERA_NAMES],
]
CAMERA_SOURCE_INTERACTION_FEATURES = [
    f"{source}_x_{camera_feature}"
    for source in SOURCE_FEATURES
    for camera_feature in CAMERA_PAYLOAD_FEATURES
]
IMAGE_STAT_FEATURES = [
    "image_luma_mean",
    "image_luma_std",
    "image_edge_mean",
    *[f"camera_{name.lower()}_luma_mean" for name in CAMERA_NAMES],
    *[f"camera_{name.lower()}_luma_std" for name in CAMERA_NAMES],
    *[f"camera_{name.lower()}_edge_mean" for name in CAMERA_NAMES],
]
IMAGE_SOURCE_INTERACTION_FEATURES = [
    f"{source}_x_{image_feature}"
    for source in SOURCE_FEATURES
    for image_feature in IMAGE_STAT_FEATURES
]
SOURCE_NUMERIC_FEATURES = [*DEFAULT_NUMERIC_FEATURES, *SOURCE_FEATURES]
INTENT_CONTEXTUAL_NUMERIC_FEATURES = [*SOURCE_NUMERIC_FEATURES, *CONTEXT_FEATURES, *INTENT_INTERACTION_FEATURES]
CONTEXTUAL_NUMERIC_FEATURES = [*SOURCE_NUMERIC_FEATURES, *CONTEXT_FEATURES, *CONTEXT_INTERACTION_FEATURES]
WORLD_CONTEXTUAL_NUMERIC_FEATURES = [*CONTEXTUAL_NUMERIC_FEATURES, *WORLD_CANDIDATE_FEATURES]
WORLD_PRIOR_CONTEXTUAL_NUMERIC_FEATURES = [*CONTEXTUAL_NUMERIC_FEATURES, *WORLD_PRIOR_FEATURES]
GEOMETRY_CONTEXTUAL_NUMERIC_FEATURES = [*CONTEXTUAL_NUMERIC_FEATURES, *GEOMETRY_PRIOR_FEATURES]
RELATIVE_CONTEXTUAL_NUMERIC_FEATURES = [
    *GEOMETRY_CONTEXTUAL_NUMERIC_FEATURES,
    *FRAME_RELATIVE_FEATURES,
]
RELATIVE_WORLD_PRIOR_CONTEXTUAL_NUMERIC_FEATURES = [
    *RELATIVE_CONTEXTUAL_NUMERIC_FEATURES,
    *WORLD_PRIOR_FEATURES,
]
RELATIVE_CONFIDENCE_CONTEXTUAL_NUMERIC_FEATURES = [
    *RELATIVE_CONTEXTUAL_NUMERIC_FEATURES,
    *CANDIDATE_MODEL_FEATURES,
]
RELATIVE_RETRIEVAL_LATENT_CONTEXTUAL_NUMERIC_FEATURES = [
    *RELATIVE_CONTEXTUAL_NUMERIC_FEATURES,
    *CANDIDATE_MODEL_FEATURES,
    *WORLD_PRIOR_FEATURES,
    *RETRIEVAL_LATENT_DISAGREEMENT_FEATURES,
]
RELATIVE_PRECEDENT_LATENT_CONTEXTUAL_NUMERIC_FEATURES = [
    *RELATIVE_CONTEXTUAL_NUMERIC_FEATURES,
    *WORLD_PRIOR_FEATURES,
    *FAMILY_RELIABILITY_FEATURES,
    *RETRIEVAL_LATENT_DISAGREEMENT_FEATURES,
]
FAMILY_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES = [
    *WORLD_CONTEXTUAL_NUMERIC_FEATURES,
    *FAMILY_RELIABILITY_FEATURES,
]
EXTERNAL_CONTEXTUAL_NUMERIC_FEATURES = [
    *FAMILY_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES,
    *EXTERNAL_EMBEDDING_FEATURES,
    *EXTERNAL_EMBEDDING_SOURCE_INTERACTION_FEATURES,
]
CONTEXTUAL_EXTERNAL_NUMERIC_FEATURES = [
    *CONTEXTUAL_NUMERIC_FEATURES,
    *EXTERNAL_EMBEDDING_FEATURES,
    *EXTERNAL_EMBEDDING_SOURCE_INTERACTION_FEATURES,
]
LEARNED_RELIABILITY_SIGNAL_NUMERIC_FEATURES = [
    *CONTEXTUAL_NUMERIC_FEATURES,
    *LEARNED_RELIABILITY_FEATURES,
]
LEARNED_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES = [
    *CONTEXTUAL_NUMERIC_FEATURES,
    *WORLD_CANDIDATE_FEATURES,
    *GEOMETRY_PRIOR_FEATURES,
    *FRAME_RELATIVE_FEATURES,
    *FAMILY_RELIABILITY_FEATURES,
    *LEARNED_RELIABILITY_FEATURES,
]
LEARNED_RELIABILITY_CONFIDENCE_CONTEXTUAL_NUMERIC_FEATURES = [
    *LEARNED_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES,
    *CANDIDATE_MODEL_FEATURES,
]
LEARNED_RELIABILITY_EXTERNAL_NUMERIC_FEATURES = [
    *LEARNED_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES,
    *EXTERNAL_EMBEDDING_FEATURES,
    *EXTERNAL_EMBEDDING_SOURCE_INTERACTION_FEATURES,
]
CAMERA_CONTEXTUAL_NUMERIC_FEATURES = [
    *CONTEXTUAL_NUMERIC_FEATURES,
    *CAMERA_PAYLOAD_FEATURES,
    *CAMERA_SOURCE_INTERACTION_FEATURES,
]
IMAGE_CONTEXTUAL_NUMERIC_FEATURES = [
    *CAMERA_CONTEXTUAL_NUMERIC_FEATURES,
    *IMAGE_STAT_FEATURES,
    *IMAGE_SOURCE_INTERACTION_FEATURES,
]
SQUARED_NUMERIC_FEATURES = [*SOURCE_NUMERIC_FEATURES, *[f"sq_{name}" for name in SOURCE_NUMERIC_FEATURES]]


@dataclass(frozen=True)
class WodPreferenceRanker:
    numeric_features: list[str]
    candidate_names: list[str]
    candidate_families: list[str]
    feature_mean: Sequence[float]
    feature_scale: Sequence[float]
    weights: Sequence[float]
    bias: float

    def __post_init__(self) -> None:
        safe_scale = [scale if abs(float(scale)) > 1e-12 else 1.0 for scale in self.feature_scale]
        weight_over_scale = [
            float(weight) / float(scale)
            for weight, scale in zip(self.weights, safe_scale)
        ]
        numeric_count = len(self.numeric_features)
        candidate_count = len(self.candidate_names)
        family_count = len(self.candidate_families)
        onehot_start = numeric_count
        onehot_end = numeric_count + candidate_count + family_count
        zero_onehot_bias = 0.0
        limit = min(onehot_end, len(self.feature_mean), len(self.weights), len(safe_scale))
        for index in range(onehot_start, limit):
            zero_onehot_bias += ((0.0 - float(self.feature_mean[index])) / float(safe_scale[index])) * float(
                self.weights[index]
            )
        object.__setattr__(self, "_safe_feature_scale", safe_scale)
        object.__setattr__(self, "_weight_over_scale", weight_over_scale)
        object.__setattr__(
            self,
            "_candidate_index_by_name",
            {name: index for index, name in enumerate(self.candidate_names)},
        )
        object.__setattr__(
            self,
            "_candidate_family_index_by_name",
            {family: index for index, family in enumerate(self.candidate_families)},
        )
        object.__setattr__(self, "_zero_onehot_bias", zero_onehot_bias)

    @classmethod
    def load(cls, path: str | Path) -> WodPreferenceRanker:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            numeric_features=list(payload["numeric_features"]),
            candidate_names=list(payload["candidate_names"]),
            candidate_families=list(payload.get("candidate_families", [])),
            feature_mean=_float_list(payload["feature_mean"]),
            feature_scale=_float_list(payload["feature_scale"]),
            weights=_float_list(payload["weights"]),
            bias=float(payload["bias"]),
        )

    def predict_row(self, row: dict[str, Any]) -> float:
        expected_length = len(self.numeric_features) + len(self.candidate_names) + len(self.candidate_families)
        if not (
            expected_length
            == len(self.feature_mean)
            == len(self.feature_scale)
            == len(self.weights)
            == len(self._safe_feature_scale)
            == len(self._weight_over_scale)
        ):
            raise ValueError("ranker feature vector and model parameter lengths do not match")
        features = row["features"]
        score = self.bias + self._zero_onehot_bias
        for index, name in enumerate(self.numeric_features):
            score += (float(features[name]) - float(self.feature_mean[index])) * float(self._weight_over_scale[index])
        candidate_name = str(row["candidate_name"])
        candidate_index = self._candidate_index_by_name.get(candidate_name)
        if candidate_index is not None:
            score += float(self._weight_over_scale[len(self.numeric_features) + int(candidate_index)])
        candidate_family = str(features.get("candidate_family", candidate_name))
        family_index = self._candidate_family_index_by_name.get(candidate_family)
        if family_index is not None:
            score += float(
                self._weight_over_scale[
                    len(self.numeric_features) + len(self.candidate_names) + int(family_index)
                ]
            )
        return float(score)

    def select_row(self, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            raise ValueError("at least one candidate row is required")
        return max(
            rows,
            key=lambda row: (
                self.predict_row(row),
                -int(row.get("candidate_index", 0)),
                str(row["candidate_name"]),
            ),
        )


def raw_features(
    row: dict[str, Any],
    numeric_features: Sequence[str],
    candidate_names: Sequence[str],
    candidate_families: Sequence[str] = (),
) -> list[float]:
    features = row["features"]
    values = [float(features[name]) for name in numeric_features]
    candidate_name = str(row["candidate_name"])
    candidate_family = str(features.get("candidate_family", candidate_name))
    values.extend(1.0 if candidate_name == name else 0.0 for name in candidate_names)
    values.extend(1.0 if candidate_family == family else 0.0 for family in candidate_families)
    return values


def selector_numeric_features(feature_mode: str) -> list[str]:
    if feature_mode == "linear":
        return list(SOURCE_NUMERIC_FEATURES)
    if feature_mode == "contextual":
        return list(CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "intent_contextual":
        return list(INTENT_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "world_contextual":
        return list(WORLD_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "world_prior_contextual":
        return list(WORLD_PRIOR_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "geometry_contextual":
        return list(GEOMETRY_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "relative_contextual":
        return list(RELATIVE_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "relative_world_prior_contextual":
        return list(RELATIVE_WORLD_PRIOR_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "relative_confidence_contextual":
        return list(RELATIVE_CONFIDENCE_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "relative_retrieval_latent_contextual":
        return list(RELATIVE_RETRIEVAL_LATENT_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "relative_precedent_latent_contextual":
        return list(RELATIVE_PRECEDENT_LATENT_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "family_reliability_contextual":
        return list(FAMILY_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "external_contextual":
        return list(EXTERNAL_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "contextual_external":
        return list(CONTEXTUAL_EXTERNAL_NUMERIC_FEATURES)
    if feature_mode == "learned_reliability_signal":
        return list(LEARNED_RELIABILITY_SIGNAL_NUMERIC_FEATURES)
    if feature_mode == "learned_reliability_signal_external":
        return list(LEARNED_RELIABILITY_SIGNAL_NUMERIC_FEATURES)
    if feature_mode == "learned_reliability_contextual":
        return list(LEARNED_RELIABILITY_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "learned_reliability_confidence_contextual":
        return list(LEARNED_RELIABILITY_CONFIDENCE_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "learned_reliability_external":
        return list(LEARNED_RELIABILITY_EXTERNAL_NUMERIC_FEATURES)
    if feature_mode == "camera_contextual":
        return list(CAMERA_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "image_contextual":
        return list(IMAGE_CONTEXTUAL_NUMERIC_FEATURES)
    if feature_mode == "squared":
        return list(SQUARED_NUMERIC_FEATURES)
    raise ValueError(f"unsupported selector feature mode: {feature_mode}")


def ranker_uses_camera_features(ranker: WodPreferenceRanker) -> bool:
    camera_features = set(CAMERA_PAYLOAD_FEATURES) | set(IMAGE_STAT_FEATURES)
    return any(feature in camera_features for feature in ranker.numeric_features)


def candidate_ranker_row(
    *,
    frame: WodE2EPreferenceFrame,
    trajectory: Trajectory,
    candidate_name: str,
    candidate_index: int,
    source: str,
) -> dict[str, Any]:
    source_family = candidate_source_family(source=source, candidate_name=candidate_name)
    features = trajectory_features(
        trajectory,
        candidate_name=candidate_name,
        intent=frame.intent,
        init_speed_mps=frame.init_speed_mps,
    )
    add_selector_context_features(features, source_family=source_family, frame=frame)
    return {
        "frame_name": frame.frame_name,
        "source": source_family,
        "candidate_name": candidate_name,
        "candidate_index": candidate_index,
        "features": features,
    }


def add_selector_context_features(
    features: dict[str, object],
    *,
    source_family: str,
    frame: WodE2EPreferenceFrame,
) -> None:
    _add_source_features(features, source_family)
    _add_context_features(features, frame)
    _add_world_candidate_defaults(features)
    _add_candidate_model_defaults(features)
    _add_world_prior_defaults(features)
    _add_retrieval_latent_disagreement_defaults(features)
    _add_frame_relative_defaults(features)
    _add_family_reliability_defaults(features)
    _add_learned_reliability_defaults(features)
    _add_external_embedding_features(features, frame)
    _add_context_interactions(features)
    _add_external_embedding_source_interactions(features)
    _add_camera_payload_features(features, frame)
    _add_camera_source_interactions(features)
    _add_image_stat_features(features, frame)
    _add_image_source_interactions(features)
    _add_squared_features(features)


def candidate_source_family(*, source: str, candidate_name: str) -> str:
    lowered_source = source.lower()
    lowered_name = candidate_name.lower()
    if "internvla" in lowered_source or lowered_name.startswith("internvla_"):
        return "internvla"
    if "internnav" in lowered_source or lowered_name.startswith("internnav_"):
        return "internnav"
    if (
        "system2" in lowered_source
        or "v20" in lowered_source
        or lowered_name.startswith("neural_system2_")
    ):
        return "system2"
    if "temporal" in lowered_source or lowered_name.startswith("temporal_"):
        return "temporal"
    if "world" in lowered_source or lowered_name.startswith("world_"):
        return "world"
    if "kinematic" in lowered_source or lowered_name in {"constant_velocity", "stop", "crawl", "maintain"}:
        return "kinematic"
    if "anchor" in lowered_source or lowered_name.startswith("anchor_"):
        return "anchor"
    if "scene" in lowered_source or lowered_name.startswith("scene_aux_"):
        return "scene"
    return "learned"


def speed_bin(speed_mps: float) -> str:
    if speed_mps < 1.4:
        return "stopped_or_creep"
    if speed_mps < 5.0:
        return "slow"
    if speed_mps < 11.0:
        return "urban"
    return "fast"


def _add_source_features(features: dict[str, object], source: str) -> None:
    for name in SOURCE_FEATURES:
        features[name] = 0.0
    key = f"source_{source}"
    if key in features:
        features[key] = 1.0


def _add_context_features(features: dict[str, object], frame: WodE2EPreferenceFrame) -> None:
    speed_key = f"speed_bin_{speed_bin(frame.init_speed_mps)}"
    intent_key = f"intent_{int(frame.intent)}"
    active_keys = {speed_key, intent_key}
    for name in CONTEXT_FEATURES:
        features[name] = 1.0 if name in active_keys else 0.0


def _add_world_candidate_defaults(features: dict[str, object]) -> None:
    features["world_nearest_distance"] = 0.0
    features["world_nearest_distance_log"] = 0.0
    features["world_neighbor_count"] = 0.0
    features["source_world_x_world_nearest_distance_log"] = 0.0


def _add_candidate_model_defaults(features: dict[str, object]) -> None:
    for name in CANDIDATE_MODEL_FEATURES:
        features[name] = 0.0


def _add_world_prior_defaults(features: dict[str, object]) -> None:
    for name in WORLD_PRIOR_FEATURES:
        features[name] = 0.0


def _add_retrieval_latent_disagreement_defaults(features: dict[str, object]) -> None:
    for name in RETRIEVAL_LATENT_DISAGREEMENT_FEATURES:
        features[name] = 0.0


def _add_frame_relative_defaults(features: dict[str, object]) -> None:
    for name in FRAME_RELATIVE_FEATURES:
        features[name] = 0.0


def _add_family_reliability_defaults(features: dict[str, object]) -> None:
    for name in FAMILY_RELIABILITY_FEATURES:
        features[name] = 0.0


def _add_learned_reliability_defaults(features: dict[str, object]) -> None:
    for name in LEARNED_RELIABILITY_FEATURES:
        features[name] = 0.0


def _add_external_embedding_features(features: dict[str, object], frame: WodE2EPreferenceFrame) -> None:
    values = list(frame.external_embedding or [])
    for index, name in enumerate(EXTERNAL_EMBEDDING_FEATURES):
        features[name] = float(values[index]) if index < len(values) else 0.0


def _add_context_interactions(features: dict[str, object]) -> None:
    for source in SOURCE_FEATURES:
        source_value = float(features[source])
        for context in CONTEXT_FEATURES:
            features[f"{source}_x_{context}"] = source_value * float(features[context])


def _add_external_embedding_source_interactions(features: dict[str, object]) -> None:
    for source in SOURCE_FEATURES:
        source_value = float(features[source])
        for feature in EXTERNAL_EMBEDDING_FEATURES:
            features[f"{source}_x_{feature}"] = source_value * float(features[feature])


def _add_squared_features(features: dict[str, object]) -> None:
    for name in SOURCE_NUMERIC_FEATURES:
        value = float(features[name])
        features[f"sq_{name}"] = value * value


def _add_camera_payload_features(features: dict[str, object], frame: WodE2EPreferenceFrame) -> None:
    by_name = {image.name: len(image.jpeg) for image in frame.camera_images}
    total_bytes = sum(by_name.values())
    count = len(by_name)
    features["camera_count"] = float(count)
    features["camera_payload_bytes_total_log"] = _log1p(total_bytes)
    features["camera_payload_bytes_mean_log"] = _log1p(total_bytes / count) if count else 0.0
    for name in CAMERA_NAMES:
        bytes_len = by_name.get(name, 0)
        prefix = f"camera_{name.lower()}"
        features[f"{prefix}_present"] = 1.0 if bytes_len else 0.0
        features[f"{prefix}_bytes_log"] = _log1p(bytes_len)


def _add_camera_source_interactions(features: dict[str, object]) -> None:
    for source in SOURCE_FEATURES:
        source_value = float(features[source])
        for camera_feature in CAMERA_PAYLOAD_FEATURES:
            features[f"{source}_x_{camera_feature}"] = source_value * float(features[camera_feature])


def _add_image_stat_features(features: dict[str, object], frame: WodE2EPreferenceFrame) -> None:
    stats_by_name = {image.name: _jpeg_luma_stats(image.jpeg) for image in frame.camera_images}
    luma_means = [stats[0] for stats in stats_by_name.values()]
    luma_stds = [stats[1] for stats in stats_by_name.values()]
    edge_means = [stats[2] for stats in stats_by_name.values()]
    features["image_luma_mean"] = _mean_or_zero(luma_means)
    features["image_luma_std"] = _mean_or_zero(luma_stds)
    features["image_edge_mean"] = _mean_or_zero(edge_means)
    for name in CAMERA_NAMES:
        luma_mean, luma_std, edge_mean = stats_by_name.get(name, (0.0, 0.0, 0.0))
        prefix = f"camera_{name.lower()}"
        features[f"{prefix}_luma_mean"] = luma_mean
        features[f"{prefix}_luma_std"] = luma_std
        features[f"{prefix}_edge_mean"] = edge_mean


def _add_image_source_interactions(features: dict[str, object]) -> None:
    for source in SOURCE_FEATURES:
        source_value = float(features[source])
        for image_feature in IMAGE_STAT_FEATURES:
            features[f"{source}_x_{image_feature}"] = source_value * float(features[image_feature])


def _jpeg_luma_stats(jpeg: bytes) -> tuple[float, float, float]:
    image = _decode_jpeg_luma(jpeg)
    if image is None or image.size == 0:
        return (0.0, 0.0, 0.0)
    normalized = image.astype(np.float32) / 255.0
    dx = np.abs(np.diff(normalized, axis=1)).mean() if normalized.shape[1] > 1 else 0.0
    dy = np.abs(np.diff(normalized, axis=0)).mean() if normalized.shape[0] > 1 else 0.0
    return (float(normalized.mean()), float(normalized.std()), float((dx + dy) * 0.5))


def _decode_jpeg_luma(jpeg: bytes) -> np.ndarray | None:
    try:
        from PIL import Image

        with Image.open(BytesIO(jpeg)) as image:
            return np.asarray(image.convert("L"))
    except Exception:
        pass
    try:
        import tensorflow as tf

        decoded = tf.image.decode_jpeg(jpeg, channels=1)
        return np.asarray(decoded.numpy()).squeeze(axis=-1)
    except Exception:
        return None


def _mean_or_zero(values: Sequence[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _log1p(value: float) -> float:
    return math.log1p(max(0.0, float(value)))


def _float_list(values: Sequence[Any]) -> list[float]:
    return [float(value) for value in values]
