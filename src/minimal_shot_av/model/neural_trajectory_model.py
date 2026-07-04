from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .learned_trajectory_model import (
    FEATURE_SET_BASE,
    FEATURE_SET_EXTERNAL_EMBEDDINGS,
    FEATURE_SET_TEMPORAL,
    FUTURE_WAYPOINTS,
    OUTPUT_DIM,
    _frame_features,
    _output_from_trajectory,
    _trajectory_from_output,
)
from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame


NEURAL_MODEL_TYPE = "neural_anchor_residual_trajectory_model_v1"


@dataclass(frozen=True)
class NeuralAnchorResidualTrajectoryModel:
    feature_set: str
    external_embedding_dimension: int
    feature_mean: list[float]
    feature_scale: list[float]
    anchors: list[list[float]]
    input_weights: list[list[float]]
    input_bias: list[float]
    anchor_head_weights: list[list[float]]
    anchor_head_bias: list[float]
    residual_head_weights: list[list[float]]
    residual_head_bias: list[float]
    residual_modes: list[list[list[float]]]
    residual_scales: list[list[float]]
    hidden_dim: int
    train_rows: int
    seed: int

    def candidate_trajectories_for_frame(
        self,
        frame: WodE2EPreferenceFrame,
        *,
        top_k: int = 8,
        residual_modes_per_anchor: int = 0,
    ) -> list[tuple[str, Trajectory, float]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        features = np.asarray([self._features(frame)], dtype=np.float64)
        hidden = _relu(features @ np.asarray(self.input_weights) + np.asarray(self.input_bias))
        logits = hidden @ np.asarray(self.anchor_head_weights) + np.asarray(self.anchor_head_bias)
        residual_flat = hidden @ np.asarray(self.residual_head_weights) + np.asarray(self.residual_head_bias)
        anchor_count = len(self.anchors)
        residuals = residual_flat.reshape((anchor_count, OUTPUT_DIM))
        order = np.argsort(-logits[0])[: min(top_k, anchor_count)]
        candidates: list[tuple[str, Trajectory, float]] = []
        anchors = np.asarray(self.anchors, dtype=np.float64)
        for rank, anchor_index_raw in enumerate(order):
            anchor_index = int(anchor_index_raw)
            output = anchors[anchor_index] + residuals[anchor_index]
            confidence = float(logits[0, anchor_index])
            candidates.append(
                (
                    f"neural_anchor_{anchor_index}_rank{rank}",
                    _trajectory_from_output(output),
                    confidence,
                )
            )
            for mode_index, (mode, scale) in enumerate(
                zip(self.residual_modes[anchor_index], self.residual_scales[anchor_index])
            ):
                if mode_index >= residual_modes_per_anchor:
                    break
                mode_vector = np.asarray(mode, dtype=np.float64) * float(scale)
                for suffix, sign in (("plus", 1.0), ("minus", -1.0)):
                    candidates.append(
                        (
                            f"neural_anchor_{anchor_index}_rank{rank}_pc{mode_index + 1}_{suffix}",
                            _trajectory_from_output(output + sign * mode_vector),
                            confidence,
                        )
                    )
        return candidates

    def _features(self, frame: WodE2EPreferenceFrame) -> list[float]:
        raw = np.asarray(
            _frame_features(
                frame.past_trajectory,
                intent=frame.intent,
                init_speed_mps=frame.init_speed_mps,
                feature_set=self.feature_set,
                external_embedding=frame.external_embedding,
            ),
            dtype=np.float64,
        )
        mean = np.asarray(self.feature_mean, dtype=np.float64)
        scale = np.asarray(self.feature_scale, dtype=np.float64)
        return ((raw - mean) / scale).tolist()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": NEURAL_MODEL_TYPE,
            "future_waypoints": FUTURE_WAYPOINTS,
            "output_dim": OUTPUT_DIM,
            "feature_set": self.feature_set,
            "external_embedding_dimension": int(self.external_embedding_dimension),
            "feature_mean": self.feature_mean,
            "feature_scale": self.feature_scale,
            "anchors": self.anchors,
            "input_weights": self.input_weights,
            "input_bias": self.input_bias,
            "anchor_head_weights": self.anchor_head_weights,
            "anchor_head_bias": self.anchor_head_bias,
            "residual_head_weights": self.residual_head_weights,
            "residual_head_bias": self.residual_head_bias,
            "residual_modes": self.residual_modes,
            "residual_scales": self.residual_scales,
            "hidden_dim": int(self.hidden_dim),
            "train_rows": int(self.train_rows),
            "seed": int(self.seed),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NeuralAnchorResidualTrajectoryModel":
        if payload.get("model_type") != NEURAL_MODEL_TYPE:
            raise ValueError(f"unsupported trajectory model type: {payload.get('model_type')!r}")
        return cls(
            feature_set=str(payload.get("feature_set", FEATURE_SET_BASE)),
            external_embedding_dimension=int(payload.get("external_embedding_dimension", 0)),
            feature_mean=_float_list(payload["feature_mean"]),
            feature_scale=_float_list(payload["feature_scale"]),
            anchors=[_float_list(row) for row in payload["anchors"]],
            input_weights=[_float_list(row) for row in payload["input_weights"]],
            input_bias=_float_list(payload["input_bias"]),
            anchor_head_weights=[_float_list(row) for row in payload["anchor_head_weights"]],
            anchor_head_bias=_float_list(payload["anchor_head_bias"]),
            residual_head_weights=[_float_list(row) for row in payload["residual_head_weights"]],
            residual_head_bias=_float_list(payload["residual_head_bias"]),
            residual_modes=[
                [_float_list(mode) for mode in anchor_modes]
                for anchor_modes in payload.get("residual_modes", [])
            ],
            residual_scales=[_float_list(scales) for scales in payload.get("residual_scales", [])],
            hidden_dim=int(payload["hidden_dim"]),
            train_rows=int(payload["train_rows"]),
            seed=int(payload["seed"]),
        )

    @classmethod
    def load(cls, path: str | Path) -> "NeuralAnchorResidualTrajectoryModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save_neural_training_frame_cache(
    frames: Iterable[WodE2EPreferenceFrame],
    path: str | Path,
    *,
    append: bool = False,
) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as output:
        for frame in frames:
            if len(frame.future_trajectory) != FUTURE_WAYPOINTS:
                continue
            output.write(json.dumps(_training_frame_to_dict(frame), sort_keys=True) + "\n")
            count += 1
    return count


def load_neural_training_frame_cache(path: str | Path) -> list[WodE2EPreferenceFrame]:
    rows: list[WodE2EPreferenceFrame] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            rows.append(_training_frame_from_dict(payload))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid neural training frame cache row {line_number}") from exc
    return rows


def fit_neural_anchor_residual_trajectory_model(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    anchor_count: int,
    hidden_dim: int = 128,
    epochs: int = 20,
    batch_size: int = 256,
    learning_rate: float = 1e-3,
    anchor_iterations: int = 25,
    residual_modes_per_anchor: int = 0,
    feature_set: str = FEATURE_SET_TEMPORAL,
    seed: int = 17,
    device: str = "auto",
) -> tuple[NeuralAnchorResidualTrajectoryModel, dict[str, Any]]:
    torch = _import_torch()
    rows = [frame for frame in frames if len(frame.future_trajectory) == FUTURE_WAYPOINTS]
    if not rows:
        raise ValueError("no frames with 20-waypoint future trajectories")
    if anchor_count <= 0:
        raise ValueError("anchor_count must be positive")
    if anchor_count > len(rows):
        raise ValueError("anchor_count cannot exceed number of training rows")
    if hidden_dim <= 0 or epochs <= 0 or batch_size <= 0 or learning_rate <= 0.0:
        raise ValueError("hidden_dim, epochs, batch_size, and learning_rate must be positive")

    rng = np.random.default_rng(seed)
    x_raw = np.asarray([_frame_features_for_model(frame, feature_set) for frame in rows], dtype=np.float64)
    y = np.asarray([_output_from_trajectory(frame.future_trajectory) for frame in rows], dtype=np.float64)
    feature_mean = x_raw.mean(axis=0)
    feature_scale = x_raw.std(axis=0)
    feature_scale[feature_scale < 1e-8] = 1.0
    x = (x_raw - feature_mean) / feature_scale
    anchors, labels = _kmeans(y, anchor_count=anchor_count, iterations=anchor_iterations, seed=seed)
    residual_targets = y - anchors[labels]
    residual_modes, residual_scales = _anchor_residual_modes(
        residual_targets,
        labels,
        anchor_count=anchor_count,
        max_modes=residual_modes_per_anchor,
    )

    selected_device = _select_torch_device(torch, device)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(int(seed))
    model = _TorchNeuralAnchorResidual(
        torch,
        input_dim=x.shape[1],
        hidden_dim=hidden_dim,
        anchor_count=anchor_count,
        output_dim=OUTPUT_DIM,
    ).to(selected_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=1e-4)
    x_tensor = torch.as_tensor(x, dtype=torch.float32, device=selected_device)
    labels_tensor = torch.as_tensor(labels, dtype=torch.long, device=selected_device)
    residual_tensor = torch.as_tensor(residual_targets, dtype=torch.float32, device=selected_device)
    history: list[dict[str, float]] = []
    row_count = x.shape[0]
    for epoch in range(int(epochs)):
        order = torch.randperm(row_count, generator=generator).to(selected_device)
        total_loss = 0.0
        total_anchor_loss = 0.0
        total_residual_loss = 0.0
        for start in range(0, row_count, int(batch_size)):
            batch_index = order[start : start + int(batch_size)]
            logits, residuals = model(x_tensor[batch_index])
            batch_labels = labels_tensor[batch_index]
            chosen = residuals[torch.arange(len(batch_index), device=selected_device), batch_labels]
            anchor_loss = torch.nn.functional.cross_entropy(logits, batch_labels)
            residual_loss = torch.nn.functional.smooth_l1_loss(chosen, residual_tensor[batch_index])
            loss = anchor_loss + residual_loss
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu()) * len(batch_index)
            total_anchor_loss += float(anchor_loss.detach().cpu()) * len(batch_index)
            total_residual_loss += float(residual_loss.detach().cpu()) * len(batch_index)
        history.append(
            {
                "epoch": float(epoch + 1),
                "loss": total_loss / row_count,
                "anchor_loss": total_anchor_loss / row_count,
                "residual_loss": total_residual_loss / row_count,
            }
        )

    state = {name: value.detach().cpu().numpy().astype(float) for name, value in model.state_dict().items()}
    result = NeuralAnchorResidualTrajectoryModel(
        feature_set=feature_set,
        external_embedding_dimension=(
            _external_embedding_dimension_for_rows(rows) if feature_set == FEATURE_SET_EXTERNAL_EMBEDDINGS else 0
        ),
        feature_mean=feature_mean.tolist(),
        feature_scale=feature_scale.tolist(),
        anchors=anchors.tolist(),
        input_weights=state["input.weight"].T.tolist(),
        input_bias=state["input.bias"].tolist(),
        anchor_head_weights=state["anchor_head.weight"].T.tolist(),
        anchor_head_bias=state["anchor_head.bias"].tolist(),
        residual_head_weights=state["residual_head.weight"].T.tolist(),
        residual_head_bias=state["residual_head.bias"].tolist(),
        residual_modes=residual_modes,
        residual_scales=residual_scales,
        hidden_dim=int(hidden_dim),
        train_rows=len(rows),
        seed=int(seed),
    )
    metadata = {
        "device": str(selected_device),
        "torch_version": str(torch.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "history": history,
        "train_rows": len(rows),
        "anchors": int(anchor_count),
        "feature_set": feature_set,
    }
    return result, metadata


def _frame_features_for_model(frame: WodE2EPreferenceFrame, feature_set: str) -> list[float]:
    return _frame_features(
        frame.past_trajectory,
        intent=frame.intent,
        init_speed_mps=frame.init_speed_mps,
        feature_set=feature_set,
        external_embedding=frame.external_embedding,
    )


def _training_frame_to_dict(frame: WodE2EPreferenceFrame) -> dict[str, Any]:
    return {
        "frame_name": frame.frame_name,
        "past_trajectory": frame.past_trajectory,
        "future_trajectory": frame.future_trajectory,
        "intent": int(frame.intent),
        "init_speed_mps": float(frame.init_speed_mps),
        "scene_tokens": frame.scene_tokens,
        "external_embedding": frame.external_embedding,
    }


def _training_frame_from_dict(payload: dict[str, Any]) -> WodE2EPreferenceFrame:
    return WodE2EPreferenceFrame(
        frame_name=str(payload["frame_name"]),
        past_trajectory=_trajectory_from_payload(payload["past_trajectory"]),
        future_trajectory=_trajectory_from_payload(payload["future_trajectory"]),
        intent=int(payload["intent"]),
        init_speed_mps=float(payload["init_speed_mps"]),
        references=[],
        scene_tokens=_optional_float_list(payload.get("scene_tokens")),
        external_embedding=_optional_float_list(payload.get("external_embedding")),
    )


def _trajectory_from_payload(payload: Sequence[Sequence[object]]) -> Trajectory:
    return [(float(point[0]), float(point[1])) for point in payload]


def _optional_float_list(payload: object) -> list[float] | None:
    if payload is None:
        return None
    return [float(value) for value in payload]


def _import_torch():
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyTorch is required to train neural WOD proposal models") from exc
    return torch


def _select_torch_device(torch, requested: str):
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("requested CUDA training, but torch.cuda.is_available() is false")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    return torch.device(requested)


class _TorchNeuralAnchorResidual:
    def __new__(cls, torch, *, input_dim: int, hidden_dim: int, anchor_count: int, output_dim: int):
        class Model(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.input = torch.nn.Linear(input_dim, hidden_dim)
                self.anchor_head = torch.nn.Linear(hidden_dim, anchor_count)
                self.residual_head = torch.nn.Linear(hidden_dim, anchor_count * output_dim)

            def forward(self, x):
                hidden = torch.relu(self.input(x))
                logits = self.anchor_head(hidden)
                residuals = self.residual_head(hidden).reshape((-1, anchor_count, output_dim))
                return logits, residuals

        return Model()


def _kmeans(rows: np.ndarray, *, anchor_count: int, iterations: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    if iterations <= 0:
        raise ValueError("anchor_iterations must be positive")
    rng = np.random.default_rng(seed)
    initial_indices = rng.choice(rows.shape[0], size=anchor_count, replace=False)
    centers = rows[initial_indices].copy()
    labels = np.zeros(rows.shape[0], dtype=np.int64)
    for _ in range(iterations):
        distances = np.sum((rows[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        labels = np.argmin(distances, axis=1)
        for index in range(anchor_count):
            mask = labels == index
            if np.any(mask):
                centers[index] = rows[mask].mean(axis=0)
    return centers, labels


def _anchor_residual_modes(
    residuals: np.ndarray,
    labels: np.ndarray,
    *,
    anchor_count: int,
    max_modes: int,
) -> tuple[list[list[list[float]]], list[list[float]]]:
    modes_by_anchor: list[list[list[float]]] = []
    scales_by_anchor: list[list[float]] = []
    for anchor_index in range(anchor_count):
        if max_modes <= 0:
            modes_by_anchor.append([])
            scales_by_anchor.append([])
            continue
        group = residuals[labels == anchor_index]
        if group.shape[0] < 2:
            modes_by_anchor.append([])
            scales_by_anchor.append([])
            continue
        centered = group - group.mean(axis=0)
        _, singular_values, vt = np.linalg.svd(centered, full_matrices=False)
        count = min(max_modes, vt.shape[0])
        denom = max(1.0, float(group.shape[0] - 1))
        modes_by_anchor.append(vt[:count].tolist())
        scales_by_anchor.append((singular_values[:count] / np.sqrt(denom)).tolist())
    return modes_by_anchor, scales_by_anchor


def _external_embedding_dimension_for_rows(rows: Sequence[WodE2EPreferenceFrame]) -> int:
    dimensions = {len(frame.external_embedding or []) for frame in rows}
    if len(dimensions) != 1 or 0 in dimensions:
        raise ValueError("external embedding feature set requires consistent non-empty embeddings")
    return int(next(iter(dimensions)))


def _relu(values: np.ndarray) -> np.ndarray:
    return np.maximum(values, 0.0)


def _float_list(values: Sequence[object]) -> list[float]:
    return [float(value) for value in values]
