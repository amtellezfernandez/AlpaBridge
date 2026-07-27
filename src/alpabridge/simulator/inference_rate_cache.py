"""Generic inference-rate throttling for trajectory-prediction policies.

Some policies can't afford to run their real forward pass every time the
driver asks for a trajectory - a heavy video/vision-action model is the
clearest case, but the same problem shows up for anything whose native
inference cadence is slower than however often it gets called. The AlpaSim
E2E challenge's ~100ms/10Hz serving budget is one place this constraint
shows up, not the reason it exists: the same need applies to any deployment
that calls a policy faster than it can afford to fully re-infer - live
simulation loops, other benchmarking harnesses, or a real vehicle's control
loop outrunning a slower perception-to-action model.

Whatever the context, the answer is the same: run inference at whatever
cadence the policy can sustain, and correctly reproject the last real
prediction onto the ego's *current* pose in between - not just replay it
unchanged, since the ego has moved and a stale ego-relative trajectory
means something different from wherever it's replayed. This module provides
that as a reusable building block: any BaseTrajectoryModel can compose a
PoseReanchoredInferenceCache instead of re-deriving this pose-transform math
for itself.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .alpasim_contract import _pose_like_to_signature


@dataclass
class CachedInference:
    anchor_time_us: int
    origin_xy: np.ndarray  # (2,) - ego position at the time of this inference
    origin_yaw: float
    relative_xy: np.ndarray  # (N, 2) positions, relative to origin at inference time


def rotate2d(vectors: np.ndarray, angle: float) -> np.ndarray:
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    rotation = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
    return vectors @ rotation.T


def reanchor_trajectory(
    cached: CachedInference, *, current_xy: np.ndarray, current_yaw: float
) -> np.ndarray:
    """Re-express a cached ego-relative trajectory relative to a new ego pose.

    A policy predicts positions relative to whatever pose was current at
    inference time. Reusing that prediction later requires converting
    through the world frame: undo the old pose's rotation/translation, then
    reapply the new one - otherwise a stale prediction gets silently
    misinterpreted relative to wherever the ego has moved to since. Headings
    aren't stored or transformed separately here - callers derive them from
    these positions' own deltas, the same way for both a fresh and a reused
    trajectory.
    """
    world_xy = cached.origin_xy + rotate2d(cached.relative_xy, cached.origin_yaw)
    return rotate2d(world_xy - current_xy, -current_yaw)


def cache_context(
    prediction_input: Any,
) -> tuple[str | None, int | None, np.ndarray | None, float | None]:
    """Extract what's needed to key/reanchor the cache, or signal that
    caching isn't possible for this call (missing session id, time, or
    pose) - in which case the caller should always run fresh inference."""
    session_uuid = getattr(prediction_input, "session_uuid", None)
    time_now_us = getattr(prediction_input, "time_now_us", None)
    ego_pose_history = getattr(prediction_input, "ego_pose_history", None) or []
    if not session_uuid or time_now_us is None or not ego_pose_history:
        return None, None, None, None
    signature = _pose_like_to_signature(ego_pose_history[-1])
    if signature is None:
        return None, None, None, None
    current_xy = np.array(signature[:2], dtype=np.float64)
    current_yaw = float(signature[2])
    return str(session_uuid), int(time_now_us), current_xy, current_yaw


class PoseReanchoredInferenceCache:
    """Throttles expensive inference to at most once per ``min_interval_s``
    per session, reprojecting the cached ego-relative trajectory onto the
    current pose in between calls via a world-frame round-trip.

    Not tied to any particular policy or deployment target - any model
    whose real inference is slower than its serving cadence can compose
    this instead of reimplementing the pose-reanchoring math itself.
    """

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval_s = float(min_interval_s)
        self._cache: dict[str, CachedInference] = {}
        self._lock = threading.Lock()

    def get(
        self, prediction_input: Any, infer: Callable[[], np.ndarray]
    ) -> tuple[np.ndarray, bool]:
        """Return (trajectory_xy, was_cached).

        ``infer()`` is called only when a fresh prediction is actually
        needed (no cache, no session context to cache against, or the
        cached prediction is older than ``min_interval_s``).
        """
        session_uuid, time_now_us, current_xy, current_yaw = cache_context(prediction_input)
        cached = self._cache.get(session_uuid) if session_uuid is not None else None
        if (
            cached is not None
            and (time_now_us - cached.anchor_time_us) / 1_000_000.0 < self._min_interval_s
        ):
            return (
                reanchor_trajectory(cached, current_xy=current_xy, current_yaw=current_yaw),
                True,
            )

        trajectory_xy = infer()
        if session_uuid is not None:
            with self._lock:
                self._cache[session_uuid] = CachedInference(
                    anchor_time_us=int(time_now_us),
                    origin_xy=current_xy,
                    origin_yaw=current_yaw,
                    relative_xy=trajectory_xy,
                )
        return trajectory_xy, False
