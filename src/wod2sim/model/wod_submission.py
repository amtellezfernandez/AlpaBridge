from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from .trajectory_io import trajectory_to_wod20_from_payload, validate_wod20_trajectory


@dataclass(frozen=True)
class WodSubmissionMetadata:
    account_name: str
    unique_method_name: str
    authors: list[str]
    affiliation: str = ""
    description: str = ""
    method_link: str = ""
    uses_public_model_pretraining: bool = False
    public_model_names: list[str] = field(default_factory=list)
    num_model_parameters: str = ""


@dataclass(frozen=True)
class WodTrajectoryPrediction:
    frame_name: str
    trajectory: list[tuple[float, float]]


def load_frame_names(path: str | Path) -> set[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    names = _frame_names_from_payload(payload)
    if not names:
        raise ValueError(f"no frame names found in {path}")
    return names


def selected_predictions_from_jsonl(
    path: str | Path,
    *,
    required_frame_names: set[str] | None = None,
    score_field: str | None = None,
    candidate_name: str | None = None,
) -> list[WodTrajectoryPrediction]:
    by_frame: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if candidate_name is not None and str(row.get("candidate_name", "")) != candidate_name:
            continue
        frame_name = str(row["frame_name"])
        if required_frame_names is not None and frame_name not in required_frame_names:
            continue
        current = by_frame.get(frame_name)
        if current is None or _candidate_key(row, score_field=score_field) > _candidate_key(
            current,
            score_field=score_field,
        ):
            by_frame[frame_name] = row

    if required_frame_names is not None:
        missing = sorted(required_frame_names - set(by_frame))
        if missing:
            preview = ", ".join(missing[:5])
            raise ValueError(f"missing predictions for {len(missing)} required frames: {preview}")
        ordered_names = sorted(required_frame_names)
    else:
        ordered_names = sorted(by_frame)
    if not ordered_names:
        raise ValueError(f"no candidate predictions found in {path}")

    return [
        WodTrajectoryPrediction(
            frame_name=frame_name,
            trajectory=trajectory_to_wod20_from_payload(by_frame[frame_name]),
        )
        for frame_name in ordered_names
    ]


def write_submission_tar(
    predictions: Sequence[WodTrajectoryPrediction],
    output_path: str | Path,
    metadata: WodSubmissionMetadata,
    *,
    member_name: str = "part0",
    num_shards: int = 1,
) -> Path:
    if not predictions:
        raise ValueError("at least one prediction is required")
    if num_shards < 1:
        raise ValueError("num_shards must be at least 1")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as tmpdir:
        # Waymo backend uses tar cvf SubDir.tar SubDir, which creates a directory
        # entry followed by part0, part1, ... — replicate that structure exactly.
        # See tutorial_vision_based_e2e_driving.ipynb packaging instructions.
        subdir = output.stem.split(".")[0]
        subdir_path = Path(tmpdir) / subdir
        subdir_path.mkdir()
        with tarfile.open(output, "w:gz") as archive:
            # Add directory entry first, as `tar cvf SubDir.tar SubDir` does.
            archive.add(subdir_path, arcname=subdir)
            for shard_index, shard_predictions in enumerate(_prediction_shards(predictions, num_shards)):
                submission = _build_submission_proto(shard_predictions, metadata)
                shard_name = member_name if num_shards == 1 else f"part{shard_index}"
                proto_path = subdir_path / shard_name
                proto_path.write_bytes(submission.SerializeToString())
                archive.add(proto_path, arcname=f"{subdir}/{shard_name}")
    return output


def read_submission_tar(path: str | Path):
    submissions = read_submission_tar_shards(path)
    if len(submissions) != 1:
        raise ValueError(f"expected one serialized proto member, found {len(submissions)}")
    return submissions[0]


def read_submission_tar_shards(path: str | Path) -> list[Any]:
    submission_pb2 = _import_submission_proto()
    submissions = []
    with tarfile.open(path, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        if not members:
            raise ValueError("expected at least one serialized proto member, found 0")
        for member in members:
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"could not read {member.name}")
            submission = submission_pb2.E2EDChallengeSubmission()
            submission.ParseFromString(extracted.read())
            submissions.append(submission)
    return submissions


def validate_submission_tar(
    path: str | Path,
    *,
    required_frame_names: set[str] | None = None,
) -> dict[str, Any]:
    submissions = read_submission_tar_shards(path)
    submission_pb2 = _import_submission_proto()
    errors: list[str] = []
    warnings: list[str] = []

    seen: set[str] = set()
    for shard_index, submission in enumerate(submissions):
        if submission.submission_type != submission_pb2.E2EDChallengeSubmission.E2ED_SUBMISSION:
            errors.append(f"shard {shard_index} submission_type is not E2ED_SUBMISSION")
        for field_name in ("account_name", "unique_method_name"):
            if not str(getattr(submission, field_name, "")).strip():
                errors.append(f"shard {shard_index} {field_name} is required")
        if not list(getattr(submission, "authors", [])):
            errors.append(f"shard {shard_index} at least one author is required")

        for index, prediction in enumerate(submission.predictions):
            frame_name = str(prediction.frame_name)
            if not frame_name:
                errors.append(f"shard {shard_index} prediction {index} has empty frame_name")
            if frame_name in seen:
                errors.append(f"duplicate prediction for frame_name={frame_name}")
            seen.add(frame_name)
            pos_x = list(prediction.trajectory.pos_x)
            pos_y = list(prediction.trajectory.pos_y)
            if len(pos_x) != 20 or len(pos_y) != 20:
                errors.append(
                    f"frame_name={frame_name} has trajectory shape "
                    f"({len(pos_x)}, {len(pos_y)}), expected (20, 20)"
                )
                continue
            try:
                validate_wod20_trajectory(list(zip(pos_x, pos_y)))
            except ValueError as exc:
                errors.append(f"frame_name={frame_name} has invalid trajectory: {exc}")

    if required_frame_names is not None:
        missing = sorted(required_frame_names - seen)
        extra = sorted(seen - required_frame_names)
        if missing:
            errors.append(f"missing {len(missing)} required frame predictions")
        if extra:
            warnings.append(f"contains {len(extra)} predictions outside required frame list")
    if not seen:
        errors.append("submission contains no predictions")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "prediction_count": len(seen),
        "shard_count": len(submissions),
        "required_frame_count": len(required_frame_names) if required_frame_names is not None else None,
    }


def _build_submission_proto(
    predictions: Sequence[WodTrajectoryPrediction],
    metadata: WodSubmissionMetadata,
):
    submission_pb2 = _import_submission_proto()
    submission = submission_pb2.E2EDChallengeSubmission()
    submission.submission_type = submission_pb2.E2EDChallengeSubmission.E2ED_SUBMISSION
    submission.account_name = metadata.account_name
    submission.unique_method_name = metadata.unique_method_name
    submission.authors.extend(metadata.authors)
    submission.affiliation = metadata.affiliation
    submission.description = metadata.description
    submission.method_link = metadata.method_link
    submission.uses_public_model_pretraining = metadata.uses_public_model_pretraining
    submission.public_model_names.extend(metadata.public_model_names)
    submission.num_model_parameters = metadata.num_model_parameters

    seen: set[str] = set()
    for prediction in predictions:
        if prediction.frame_name in seen:
            raise ValueError(f"duplicate frame prediction: {prediction.frame_name}")
        seen.add(prediction.frame_name)
        points = validate_wod20_trajectory(prediction.trajectory)
        frame_prediction = submission.predictions.add()
        frame_prediction.frame_name = prediction.frame_name
        frame_prediction.trajectory.pos_x.extend(float(x) for x, _ in points)
        frame_prediction.trajectory.pos_y.extend(float(y) for _, y in points)
    return submission


def _candidate_key(row: dict[str, Any], *, score_field: str | None) -> tuple[float, int, str]:
    score = float(row.get(score_field, 0.0)) if score_field else 0.0
    return (score, -int(row.get("candidate_index", 0)), str(row.get("candidate_name", "")))


def _prediction_shards(
    predictions: Sequence[WodTrajectoryPrediction],
    num_shards: int,
) -> list[Sequence[WodTrajectoryPrediction]]:
    predictions_per_shard = math.ceil(len(predictions) / num_shards)
    return [
        predictions[index * predictions_per_shard : (index + 1) * predictions_per_shard]
        for index in range(num_shards)
    ]


def _frame_names_from_payload(payload: Any) -> set[str]:
    if isinstance(payload, list):
        return {_frame_name_from_item(item) for item in payload}
    if isinstance(payload, dict):
        for key in ("frame_names", "test_frame_names", "required_frame_names"):
            if key in payload:
                return _frame_names_from_payload(payload[key])
        for key in ("frames", "test_frames", "required_frames"):
            if key in payload:
                return _frame_names_from_payload(payload[key])
    raise ValueError("unsupported frame-list JSON format")


def _frame_name_from_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("frame_name", "name", "context_name"):
            if key in item:
                return str(item[key])
    raise ValueError(f"unsupported frame-list item: {item!r}")


def _import_submission_proto():
    try:
        from waymo_open_dataset.protos import end_to_end_driving_submission_pb2 as submission_pb2
    except ImportError as exc:
        raise ImportError(
            "WOD-E2E submission writing requires official Waymo protos on PYTHONPATH. "
            "Run with `PYTHONPATH=.wod-protos:src` or install waymo-open-dataset."
        ) from exc
    return submission_pb2
