from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .learned_trajectory_model import FUTURE_WAYPOINTS, PAST_WAYPOINTS, OUTPUT_DIM, _trajectory_from_output
from .neural_trajectory_model import load_neural_training_frame_cache
from .rfs_metric import Trajectory
from .wod_e2e import WodE2EPreferenceFrame


TRANSFORMER_MODEL_TYPE = "transformer_trajectory_proposal_model_v1"


@dataclass(frozen=True)
class TransformerTrajectoryProposalModel:
    past_mean: list[list[float]]
    past_scale: list[list[float]]
    speed_mean: float
    speed_scale: float
    external_embedding_dimension: int
    model_config: dict[str, int | float]
    state_dict: dict[str, Any]
    train_rows: int
    seed: int

    def candidate_trajectories_for_frame(
        self,
        frame: WodE2EPreferenceFrame,
        *,
        top_k: int = 12,
    ) -> list[tuple[str, Trajectory, float]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        torch = _import_torch()
        module = _TorchTransformerProposal(torch, **_module_config(self.model_config))
        module.load_state_dict(self.state_dict)
        module.eval()
        with torch.no_grad():
            past, intent, speed, external = self._tensors_for_frame(torch, frame)
            logits, trajectories = module(past, intent, speed, external)
            limit = min(int(top_k), int(trajectories.shape[1]))
            order = torch.argsort(logits[0], descending=True)[:limit]
            candidates: list[tuple[str, Trajectory, float]] = []
            for rank, mode_index_tensor in enumerate(order):
                mode_index = int(mode_index_tensor.detach().cpu())
                output = trajectories[0, mode_index].detach().cpu().numpy().astype(float)
                confidence = float(logits[0, mode_index].detach().cpu())
                candidates.append(
                    (
                        f"transformer_mode_{mode_index}_rank{rank}",
                        _trajectory_from_output(output),
                        confidence,
                    )
                )
            return candidates

    def _tensors_for_frame(self, torch, frame: WodE2EPreferenceFrame):
        past = _normalized_past(frame.past_trajectory, self.past_mean, self.past_scale)
        speed = _normalized_speed(frame.init_speed_mps, self.speed_mean, self.speed_scale)
        external = _external_embedding(frame.external_embedding, self.external_embedding_dimension)
        return (
            torch.as_tensor([past], dtype=torch.float32),
            torch.as_tensor([int(frame.intent)], dtype=torch.long),
            torch.as_tensor([[speed]], dtype=torch.float32),
            torch.as_tensor([external], dtype=torch.float32),
        )

    @classmethod
    def load(cls, path: str | Path) -> "TransformerTrajectoryProposalModel":
        torch = _import_torch()
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        if payload.get("model_type") != TRANSFORMER_MODEL_TYPE:
            raise ValueError(f"unsupported transformer model type: {payload.get('model_type')!r}")
        return cls(
            past_mean=[[float(value) for value in row] for row in payload["past_mean"]],
            past_scale=[[float(value) for value in row] for row in payload["past_scale"]],
            speed_mean=float(payload["speed_mean"]),
            speed_scale=float(payload["speed_scale"]),
            external_embedding_dimension=int(payload.get("external_embedding_dimension", 0)),
            model_config=dict(payload["model_config"]),
            state_dict=payload["state_dict"],
            train_rows=int(payload["train_rows"]),
            seed=int(payload["seed"]),
        )

    def save(self, path: str | Path) -> None:
        torch = _import_torch()
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_type": TRANSFORMER_MODEL_TYPE,
                "past_mean": self.past_mean,
                "past_scale": self.past_scale,
                "speed_mean": float(self.speed_mean),
                "speed_scale": float(self.speed_scale),
                "external_embedding_dimension": int(self.external_embedding_dimension),
                "model_config": self.model_config,
                "state_dict": self.state_dict,
                "train_rows": int(self.train_rows),
                "seed": int(self.seed),
            },
            output_path,
        )


def fit_transformer_trajectory_proposal_model(
    frames: Iterable[WodE2EPreferenceFrame],
    *,
    hidden_dim: int = 256,
    layers: int = 4,
    heads: int = 8,
    modes: int = 12,
    epochs: int = 80,
    batch_size: int = 128,
    learning_rate: float = 3e-4,
    smoothness_weight: float = 0.02,
    confidence_weight: float = 0.2,
    seed: int = 17,
    device: str = "auto",
) -> tuple[TransformerTrajectoryProposalModel, dict[str, Any]]:
    torch = _import_torch()
    rows = [frame for frame in frames if len(frame.future_trajectory) == FUTURE_WAYPOINTS]
    if not rows:
        raise ValueError("no frames with 20-waypoint future trajectories")
    _validate_training_args(hidden_dim, layers, heads, modes, epochs, batch_size, learning_rate)
    selected_device = _select_torch_device(torch, device)
    torch.manual_seed(int(seed))

    past_raw = np.asarray([_pad_recent_points(frame.past_trajectory) for frame in rows], dtype=np.float32)
    y_raw = np.asarray([_future_output(frame.future_trajectory) for frame in rows], dtype=np.float32)
    speed_raw = np.asarray([[float(frame.init_speed_mps)] for frame in rows], dtype=np.float32)
    external_dim = _external_embedding_dimension(rows)
    external_raw = np.asarray(
        [_external_embedding(frame.external_embedding, external_dim) for frame in rows],
        dtype=np.float32,
    )
    past_mean = past_raw.mean(axis=0)
    past_scale = past_raw.std(axis=0)
    past_scale[past_scale < 1e-6] = 1.0
    speed_mean = float(speed_raw.mean())
    speed_scale = float(speed_raw.std())
    if speed_scale < 1e-6:
        speed_scale = 1.0

    past_tensor = torch.as_tensor((past_raw - past_mean) / past_scale, dtype=torch.float32, device=selected_device)
    speed_tensor = torch.as_tensor((speed_raw - speed_mean) / speed_scale, dtype=torch.float32, device=selected_device)
    external_tensor = torch.as_tensor(external_raw, dtype=torch.float32, device=selected_device)
    intent_tensor = torch.as_tensor([int(frame.intent) for frame in rows], dtype=torch.long, device=selected_device)
    target_tensor = torch.as_tensor(y_raw, dtype=torch.float32, device=selected_device)

    config = {
        "hidden_dim": int(hidden_dim),
        "layers": int(layers),
        "heads": int(heads),
        "modes": int(modes),
        "external_embedding_dimension": int(external_dim),
    }
    module = _TorchTransformerProposal(torch, **_module_config(config)).to(selected_device)
    optimizer = torch.optim.AdamW(module.parameters(), lr=float(learning_rate), weight_decay=1e-4)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(int(seed))
    row_count = len(rows)
    history: list[dict[str, float]] = []
    for epoch in range(int(epochs)):
        order = torch.randperm(row_count, generator=generator).to(selected_device)
        totals = {"loss": 0.0, "trajectory_loss": 0.0, "confidence_loss": 0.0, "smoothness_loss": 0.0}
        for start in range(0, row_count, int(batch_size)):
            batch = order[start : start + int(batch_size)]
            logits, trajectories = module(
                past_tensor[batch],
                intent_tensor[batch],
                speed_tensor[batch],
                external_tensor[batch],
            )
            loss, parts = _proposal_loss(
                torch,
                logits,
                trajectories,
                target_tensor[batch],
                confidence_weight=float(confidence_weight),
                smoothness_weight=float(smoothness_weight),
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            batch_size_actual = int(len(batch))
            for key in totals:
                totals[key] += float(parts[key].detach().cpu()) * batch_size_actual
        history.append({"epoch": float(epoch + 1), **{key: value / row_count for key, value in totals.items()}})

    model = TransformerTrajectoryProposalModel(
        past_mean=past_mean.astype(float).tolist(),
        past_scale=past_scale.astype(float).tolist(),
        speed_mean=speed_mean,
        speed_scale=speed_scale,
        external_embedding_dimension=external_dim,
        model_config=config,
        state_dict={key: value.detach().cpu() for key, value in module.state_dict().items()},
        train_rows=row_count,
        seed=int(seed),
    )
    metadata = {
        "schema": "wod_transformer_trajectory_train_report_v1",
        "device": str(selected_device),
        "torch_version": str(torch.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "history": history,
        "train_rows": row_count,
        "hidden_dim": int(hidden_dim),
        "layers": int(layers),
        "heads": int(heads),
        "modes": int(modes),
        "external_embedding_dimension": int(external_dim),
    }
    return model, metadata


def load_transformer_training_frame_cache(path: str | Path) -> list[WodE2EPreferenceFrame]:
    return load_neural_training_frame_cache(path)


def _proposal_loss(torch, logits, trajectories, target, *, confidence_weight: float, smoothness_weight: float):
    per_mode = torch.nn.functional.smooth_l1_loss(
        trajectories,
        target[:, None, :].expand_as(trajectories),
        reduction="none",
    ).mean(dim=2)
    trajectory_loss, best_mode = per_mode.min(dim=1)
    confidence_loss = torch.nn.functional.cross_entropy(logits, best_mode)
    points = trajectories.reshape((trajectories.shape[0], trajectories.shape[1], FUTURE_WAYPOINTS, 2))
    second_diff = points[:, :, 2:] - 2.0 * points[:, :, 1:-1] + points[:, :, :-2]
    smoothness_loss = torch.mean(second_diff * second_diff)
    total = trajectory_loss.mean() + confidence_weight * confidence_loss + smoothness_weight * smoothness_loss
    return total, {
        "loss": total,
        "trajectory_loss": trajectory_loss.mean(),
        "confidence_loss": confidence_loss,
        "smoothness_loss": smoothness_loss,
    }


def _module_config(config: dict[str, int | float]) -> dict[str, int]:
    return {
        "hidden_dim": int(config["hidden_dim"]),
        "layers": int(config["layers"]),
        "heads": int(config["heads"]),
        "modes": int(config["modes"]),
        "external_embedding_dimension": int(config.get("external_embedding_dimension", 0)),
    }


def _validate_training_args(
    hidden_dim: int,
    layers: int,
    heads: int,
    modes: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
) -> None:
    if min(hidden_dim, layers, heads, modes, epochs, batch_size) <= 0 or learning_rate <= 0.0:
        raise ValueError("hidden_dim, layers, heads, modes, epochs, batch_size, and learning_rate must be positive")
    if hidden_dim % heads != 0:
        raise ValueError("hidden_dim must be divisible by heads")


def _normalized_past(
    trajectory: Sequence[tuple[float, float]],
    mean: Sequence[Sequence[float]],
    scale: Sequence[Sequence[float]],
) -> list[list[float]]:
    past = np.asarray(_pad_recent_points(trajectory), dtype=np.float32)
    return ((past - np.asarray(mean, dtype=np.float32)) / np.asarray(scale, dtype=np.float32)).tolist()


def _normalized_speed(value: float, mean: float, scale: float) -> float:
    return float((float(value) - float(mean)) / float(scale))


def _pad_recent_points(trajectory: Sequence[tuple[float, float]]) -> list[list[float]]:
    points = [[float(x), float(y)] for x, y in trajectory[-PAST_WAYPOINTS:]]
    if not points:
        points = [[0.0, 0.0]]
    while len(points) < PAST_WAYPOINTS:
        points.insert(0, points[0])
    return points


def _future_output(trajectory: Sequence[tuple[float, float]]) -> list[float]:
    values: list[float] = []
    for x, y in trajectory[:FUTURE_WAYPOINTS]:
        values.extend([float(x), float(y)])
    return values


def _external_embedding(values: Sequence[float] | None, dimension: int) -> list[float]:
    if dimension <= 0:
        return []
    if values is None:
        return [0.0] * dimension
    result = [float(value) for value in values[:dimension]]
    return result + [0.0] * (dimension - len(result))


def _external_embedding_dimension(frames: Sequence[WodE2EPreferenceFrame]) -> int:
    for frame in frames:
        if frame.external_embedding:
            return len(frame.external_embedding)
    return 0


def _import_torch():
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyTorch is required for transformer WOD proposal models") from exc
    return torch


def _select_torch_device(torch, requested: str):
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("requested CUDA training, but torch.cuda.is_available() is false")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    return torch.device(requested)


class _TorchTransformerProposal:
    def __new__(
        cls,
        torch,
        *,
        hidden_dim: int,
        layers: int,
        heads: int,
        modes: int,
        external_embedding_dimension: int,
    ):
        class Model(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.past_projection = torch.nn.Linear(2, hidden_dim)
                self.intent_embedding = torch.nn.Embedding(8, hidden_dim)
                self.speed_projection = torch.nn.Linear(1, hidden_dim)
                self.external_projection = (
                    torch.nn.Linear(external_embedding_dimension, hidden_dim)
                    if external_embedding_dimension > 0
                    else None
                )
                encoder_layer = torch.nn.TransformerEncoderLayer(
                    d_model=hidden_dim,
                    nhead=heads,
                    dim_feedforward=hidden_dim * 4,
                    dropout=0.05,
                    batch_first=True,
                    activation="gelu",
                )
                self.encoder = torch.nn.TransformerEncoder(encoder_layer, num_layers=layers)
                self.logit_head = torch.nn.Linear(hidden_dim, modes)
                self.trajectory_head = torch.nn.Linear(hidden_dim, modes * OUTPUT_DIM)
                self.modes = modes

            def forward(self, past, intent, speed, external):
                tokens = [self.past_projection(past)]
                intent_token = self.intent_embedding(torch.clamp(intent, 0, 7)).unsqueeze(1)
                tokens.append(intent_token)
                tokens.append(self.speed_projection(speed).unsqueeze(1))
                if self.external_projection is not None:
                    tokens.append(self.external_projection(external).unsqueeze(1))
                encoded = self.encoder(torch.cat(tokens, dim=1))
                pooled = encoded.mean(dim=1)
                logits = self.logit_head(pooled)
                trajectories = self.trajectory_head(pooled).reshape((-1, self.modes, OUTPUT_DIM))
                return logits, trajectories

        return Model()
