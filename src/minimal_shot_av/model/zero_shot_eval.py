from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field, replace
import importlib.util
import json
import statistics
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from .rfs_metric import ManeuverCandidate, Trajectory, score_candidate
from .trajectory_io import trajectory_to_wod20_from_payload
from .wod_e2e import WodE2EPreferenceFrame
from .wod_ranker import WodPreferenceRanker, candidate_ranker_row


@dataclass(frozen=True)
class CandidateRecord:
    frame_name: str
    trajectory: Trajectory
    source: str = "candidate_file"
    candidate_name: str = "candidate"
    candidate_index: int = 0
    latency_ms: float | None = None
    confidence: float | None = None


RfsScorer = Callable[[CandidateRecord, WodE2EPreferenceFrame], float]


class CandidateSelectionMode(str, Enum):
    FIRST = "first"
    RANKER = "ranker"
    BEST_VALIDATION = "best_validation"


@dataclass(frozen=True)
class FrameEvaluation:
    frame_name: str
    source: str
    rfs: float
    reference_count: int
    init_speed_mps: float
    latency_ms: float | None = None
    candidate_count: int = 1
    selected_candidate_index: int = 0
    best_candidate_rfs: float | None = None
    best_candidate_source: str | None = None
    best_candidate_index: int | None = None
    selection_regret: float | None = None
    best_reference_label: str | None = None
    best_reference_score: float | None = None
    best_reference_error_3s_m: float | None = None
    best_reference_error_5s_m: float | None = None
    closest_3s_reference_label: str | None = None
    closest_3s_error_m: float | None = None
    closest_5s_reference_label: str | None = None
    closest_5s_error_m: float | None = None


@dataclass(frozen=True)
class ZeroShotEvaluationReport:
    evaluated_frames: int
    missing_candidate_frames: int
    invalid_candidate_records: int
    invalid_candidate_examples: list[str]
    mean_rfs: float | None
    median_rfs: float | None
    min_rfs: float | None
    max_rfs: float | None
    mean_best_candidate_rfs: float | None
    mean_selection_regret: float | None
    mean_latency_ms: float | None
    score_backend: str
    candidate_selection_mode: str
    ranker_unseen_candidate_names: list[str]
    ranker_unseen_candidate_families: list[str]
    scanned_preference_frames: int
    evaluations: list[FrameEvaluation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_candidate_records(path: str | Path) -> tuple[dict[str, CandidateRecord], list[str]]:
    groups, invalid = load_candidate_record_groups(path)
    return {frame_name: records[0] for frame_name, records in groups.items() if records}, invalid


def load_candidate_record_groups(path: str | Path) -> tuple[dict[str, list[CandidateRecord]], list[str]]:
    records_by_frame: dict[str, list[CandidateRecord]] = {}
    invalid: list[str] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                record = candidate_record_from_json(payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                invalid.append(f"line {line_number}: {exc}")
                continue
            if "candidate_index" not in payload:
                record = replace(record, candidate_index=len(records_by_frame.get(record.frame_name, [])))
            records_by_frame.setdefault(record.frame_name, []).append(record)
    return records_by_frame, invalid


def candidate_record_from_json(payload: dict[str, Any]) -> CandidateRecord:
    frame_name = str(payload["frame_name"])
    source = str(payload.get("source", "candidate_file"))
    candidate_name = str(payload.get("candidate_name", source))
    candidate_index = int(payload.get("candidate_index", 0))
    if "trajectory_20wp_4hz" in payload:
        trajectory = trajectory_to_wod20_from_payload({"trajectory_20wp_4hz": payload["trajectory_20wp_4hz"]})
    elif "trajectory_64wp_10hz" in payload:
        trajectory = trajectory_to_wod20_from_payload({"trajectory_64wp_10hz": payload["trajectory_64wp_10hz"]})
    else:
        raise ValueError("record must contain trajectory_20wp_4hz or trajectory_64wp_10hz")
    latency_ms = payload.get("latency_ms")
    confidence = payload.get("confidence", payload.get("score"))
    return CandidateRecord(
        frame_name=frame_name,
        trajectory=trajectory,
        source=source,
        candidate_name=candidate_name,
        candidate_index=candidate_index,
        latency_ms=None if latency_ms is None else float(latency_ms),
        confidence=None if confidence is None else float(confidence),
    )


def evaluate_zero_shot_candidates(
    frames: Iterable[WodE2EPreferenceFrame],
    candidates: dict[str, CandidateRecord],
    *,
    scorer: RfsScorer | None = None,
    score_backend: str = "local_rfs_metric",
    invalid_candidate_records: int = 0,
    invalid_candidate_examples: list[str] | None = None,
    max_frames: int | None = None,
    max_evaluated_frames: int | None = None,
) -> ZeroShotEvaluationReport:
    return evaluate_zero_shot_candidate_groups(
        frames,
        {frame_name: [candidate] for frame_name, candidate in candidates.items()},
        scorer=scorer,
        score_backend=score_backend,
        invalid_candidate_records=invalid_candidate_records,
        invalid_candidate_examples=invalid_candidate_examples,
        max_frames=max_frames,
        max_evaluated_frames=max_evaluated_frames,
        selection_mode=CandidateSelectionMode.FIRST,
        ranker=None,
    )


def evaluate_zero_shot_candidate_groups(
    frames: Iterable[WodE2EPreferenceFrame],
    candidates_by_frame: dict[str, list[CandidateRecord]],
    *,
    scorer: RfsScorer | None = None,
    score_backend: str = "local_rfs_metric",
    invalid_candidate_records: int = 0,
    invalid_candidate_examples: list[str] | None = None,
    max_frames: int | None = None,
    max_evaluated_frames: int | None = None,
    selection_mode: CandidateSelectionMode | str = CandidateSelectionMode.FIRST,
    ranker: WodPreferenceRanker | None = None,
) -> ZeroShotEvaluationReport:
    selection_mode = CandidateSelectionMode(selection_mode)
    if selection_mode is CandidateSelectionMode.RANKER and ranker is None:
        raise ValueError("ranker selection requires a WodPreferenceRanker")
    scorer = scorer or local_rfs_score
    evaluations: list[FrameEvaluation] = []
    missing = 0
    scanned = 0
    ranker_unseen_names: set[str] = set()
    ranker_unseen_families: set[str] = set()
    unscored_frame_names = {frame_name for frame_name, records in candidates_by_frame.items() if records}
    for frame in frames:
        if max_frames is not None and scanned >= max_frames:
            break
        if max_evaluated_frames is not None and len(evaluations) >= max_evaluated_frames:
            break
        if not unscored_frame_names:
            break
        scanned += 1
        frame_candidates = candidates_by_frame.get(frame.frame_name, [])
        if not frame_candidates:
            missing += 1
            continue
        unscored_frame_names.discard(frame.frame_name)
        scored_candidates = [(float(scorer(candidate, frame)), candidate) for candidate in frame_candidates]
        best_candidate_rfs, best_candidate = max(
            scored_candidates,
            key=lambda item: (item[0], -item[1].candidate_index),
        )
        if selection_mode is CandidateSelectionMode.BEST_VALIDATION:
            rfs, candidate = best_candidate_rfs, best_candidate
        elif selection_mode is CandidateSelectionMode.RANKER:
            unseen_names, unseen_families = _ranker_unseen_candidate_metadata(frame_candidates, frame, ranker)
            ranker_unseen_names.update(unseen_names)
            ranker_unseen_families.update(unseen_families)
            candidate = _select_with_ranker(frame_candidates, frame, ranker)
            rfs = float(scorer(candidate, frame))
        else:
            rfs, candidate = scored_candidates[0]
        diagnostics = candidate_geometry_diagnostics(candidate, frame)
        evaluations.append(
            FrameEvaluation(
                frame_name=frame.frame_name,
                source=candidate.source,
                rfs=float(rfs),
                reference_count=len(frame.references),
                init_speed_mps=frame.init_speed_mps,
                latency_ms=candidate.latency_ms,
                candidate_count=len(frame_candidates),
                selected_candidate_index=candidate.candidate_index,
                best_candidate_rfs=float(best_candidate_rfs),
                best_candidate_source=best_candidate.source,
                best_candidate_index=best_candidate.candidate_index,
                selection_regret=float(best_candidate_rfs - rfs),
                **diagnostics,
            )
        )

    scores = [evaluation.rfs for evaluation in evaluations]
    best_candidate_scores = [
        evaluation.best_candidate_rfs
        for evaluation in evaluations
        if evaluation.best_candidate_rfs is not None
    ]
    selection_regrets = [
        evaluation.selection_regret
        for evaluation in evaluations
        if evaluation.selection_regret is not None
    ]
    latencies = [evaluation.latency_ms for evaluation in evaluations if evaluation.latency_ms is not None]
    return ZeroShotEvaluationReport(
        evaluated_frames=len(evaluations),
        missing_candidate_frames=missing,
        invalid_candidate_records=invalid_candidate_records,
        invalid_candidate_examples=(invalid_candidate_examples or [])[:10],
        mean_rfs=_mean(scores),
        median_rfs=None if not scores else statistics.median(scores),
        min_rfs=None if not scores else min(scores),
        max_rfs=None if not scores else max(scores),
        mean_best_candidate_rfs=_mean(best_candidate_scores),
        mean_selection_regret=_mean(selection_regrets),
        mean_latency_ms=_mean(latencies),
        score_backend=score_backend,
        candidate_selection_mode=selection_mode.value,
        ranker_unseen_candidate_names=sorted(ranker_unseen_names),
        ranker_unseen_candidate_families=sorted(ranker_unseen_families),
        scanned_preference_frames=scanned,
        evaluations=evaluations,
    )


def local_rfs_score(candidate: CandidateRecord, frame: WodE2EPreferenceFrame) -> float:
    return float(
        score_candidate(
            ManeuverCandidate(candidate.source, candidate.trajectory),
            frame.references,
            frame.init_speed_mps,
        ).combined_score
    )


def _select_with_ranker(
    candidates: list[CandidateRecord],
    frame: WodE2EPreferenceFrame,
    ranker: WodPreferenceRanker | None,
) -> CandidateRecord:
    if ranker is None:
        raise ValueError("ranker selection requires a WodPreferenceRanker")
    rows = [_ranker_row(candidate, frame) for candidate in candidates]
    selected_row = ranker.select_row(rows)
    selected_index = int(selected_row["candidate_index"])
    for candidate in candidates:
        if candidate.candidate_index == selected_index:
            return candidate
    raise RuntimeError(f"ranker selected missing candidate_index={selected_index}")


def _ranker_row(candidate: CandidateRecord, frame: WodE2EPreferenceFrame) -> dict[str, Any]:
    return candidate_ranker_row(
        frame=frame,
        trajectory=candidate.trajectory,
        candidate_name=candidate.candidate_name,
        candidate_index=candidate.candidate_index,
        source=candidate.source,
    )


def _ranker_unseen_candidate_metadata(
    candidates: list[CandidateRecord],
    frame: WodE2EPreferenceFrame,
    ranker: WodPreferenceRanker | None,
) -> tuple[set[str], set[str]]:
    if ranker is None:
        raise ValueError("ranker selection requires a WodPreferenceRanker")
    unseen_names: set[str] = set()
    unseen_families: set[str] = set()
    for candidate in candidates:
        row = _ranker_row(candidate, frame)
        candidate_name = str(row["candidate_name"])
        candidate_family = str(row["features"].get("candidate_family", candidate_name))
        if candidate_name not in ranker.candidate_names:
            unseen_names.add(candidate_name)
        if ranker.candidate_families and candidate_family not in ranker.candidate_families:
            unseen_families.add(candidate_family)
    return unseen_names, unseen_families


def candidate_geometry_diagnostics(
    candidate: CandidateRecord,
    frame: WodE2EPreferenceFrame,
) -> dict[str, float | str | None]:
    """Return model-side geometry diagnostics against validation preference references."""

    if not frame.references:
        return {
            "best_reference_label": None,
            "best_reference_score": None,
            "best_reference_error_3s_m": None,
            "best_reference_error_5s_m": None,
            "closest_3s_reference_label": None,
            "closest_3s_error_m": None,
            "closest_5s_reference_label": None,
            "closest_5s_error_m": None,
        }
    best_reference = max(frame.references, key=lambda reference: reference.score)
    closest_3s = min(
        frame.references,
        key=lambda reference: _trajectory_error(candidate.trajectory, reference.trajectory, 11),
    )
    closest_5s = min(
        frame.references,
        key=lambda reference: _trajectory_error(candidate.trajectory, reference.trajectory, 19),
    )
    return {
        "best_reference_label": best_reference.label,
        "best_reference_score": float(best_reference.score),
        "best_reference_error_3s_m": _trajectory_error(candidate.trajectory, best_reference.trajectory, 11),
        "best_reference_error_5s_m": _trajectory_error(candidate.trajectory, best_reference.trajectory, 19),
        "closest_3s_reference_label": closest_3s.label,
        "closest_3s_error_m": _trajectory_error(candidate.trajectory, closest_3s.trajectory, 11),
        "closest_5s_reference_label": closest_5s.label,
        "closest_5s_error_m": _trajectory_error(candidate.trajectory, closest_5s.trajectory, 19),
    }


def _trajectory_error(candidate: Trajectory, reference: Trajectory, index: int) -> float:
    if len(candidate) <= index or len(reference) <= index:
        return float("nan")
    dx = candidate[index][0] - reference[index][0]
    dy = candidate[index][1] - reference[index][1]
    return (dx * dx + dy * dy) ** 0.5


def load_official_rfs_scorer(waymo_src: str | Path) -> RfsScorer:
    import numpy as np

    path = Path(waymo_src) / "waymo_open_dataset" / "metrics" / "python" / "rater_feedback_utils.py"
    spec = importlib.util.spec_from_file_location("wod_rater_feedback_utils", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load official RFS utility from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def scorer(candidate: CandidateRecord, frame: WodE2EPreferenceFrame) -> float:
        outputs = module.get_rater_feedback_score(
            np.array([[candidate.trajectory]], dtype=np.float64),
            np.array([[1.0]], dtype=np.float64),
            [[np.array(reference.trajectory, dtype=np.float64) for reference in frame.references]],
            [np.array([reference.score for reference in frame.references], dtype=np.float64)],
            np.array([frame.init_speed_mps], dtype=np.float64),
        )
        return float(outputs["rater_feedback_score"][0])

    return scorer


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def main() -> int:
    from .wod_e2e import load_preference_frames

    parser = argparse.ArgumentParser(
        description="Model-only WOD-E2E zero-shot evaluator. No simulator policy or scenario code is used."
    )
    parser.add_argument(
        "--val-dir",
        type=Path,
        default=Path("workspace") / "waymo_open_dataset_end_to_end_camera_v_1_0_0" / "val",
    )
    parser.add_argument(
        "--candidate-jsonl",
        type=Path,
        required=True,
        help="JSONL with frame_name and trajectory fields.",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts") / "wod_zero_shot_rfs.json")
    parser.add_argument(
        "--rfs-backend",
        choices=("official", "local"),
        default="official",
        help="Use official Waymo RFS for final reports; local is for fast smoke tests.",
    )
    parser.add_argument(
        "--diagnostics-only",
        action="store_true",
        help="Write matched candidate/reference geometry diagnostics without invoking the official scorer.",
    )
    parser.add_argument(
        "--waymo-src",
        type=Path,
        default=Path("workspace") / "waymo-open-dataset" / "src",
        help="Path containing waymo_open_dataset/metrics/python/rater_feedback_utils.py.",
    )
    parser.add_argument("--max-shards", type=int)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--max-preference-frames", type=int, help="Maximum preference frames to scan.")
    parser.add_argument("--max-evaluated-frames", type=int, help="Maximum matched candidate frames to score.")
    parser.add_argument(
        "--candidate-selection",
        choices=tuple(mode.value for mode in CandidateSelectionMode),
        default="first",
        help="'ranker' requires --ranker; 'best_validation' is validation-only headroom.",
    )
    parser.add_argument("--ranker", type=Path, help="Saved WOD preference ranker JSON for ranker candidate selection.")
    args = parser.parse_args()

    frames = load_preference_frames(
        args.val_dir,
        max_shards=args.max_shards,
        max_records=args.max_records,
        include_camera_images=False,
    )

    candidate_groups, invalid = load_candidate_record_groups(args.candidate_jsonl)
    scorer = local_rfs_score
    score_backend = "local_rfs_metric"
    if args.diagnostics_only:
        score_backend = "geometry_diagnostics_only"
    elif args.rfs_backend == "official":
        scorer = load_official_rfs_scorer(args.waymo_src)
        score_backend = "official_waymo_rfs"
    ranker = WodPreferenceRanker.load(args.ranker) if args.ranker is not None else None
    report = evaluate_zero_shot_candidate_groups(
        frames,
        candidate_groups,
        scorer=scorer,
        score_backend=score_backend,
        invalid_candidate_records=len(invalid),
        invalid_candidate_examples=invalid,
        max_frames=args.max_preference_frames,
        max_evaluated_frames=args.max_evaluated_frames,
        selection_mode=args.candidate_selection,
        ranker=ranker,
    )
    if report.evaluated_frames == 0:
        raise RuntimeError("no candidate records matched WOD-E2E preference frames")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "evaluations"}, indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
