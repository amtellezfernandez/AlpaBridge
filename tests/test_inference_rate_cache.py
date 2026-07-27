from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from alpabridge.simulator.inference_rate_cache import (
    CachedInference,
    PoseReanchoredInferenceCache,
    cache_context,
    reanchor_trajectory,
    rotate2d,
)


def test_rotate2d_identity_at_zero_angle() -> None:
    vectors = np.array([[1.0, 0.0], [0.0, 1.0], [3.0, -2.0]])

    np.testing.assert_allclose(rotate2d(vectors, 0.0), vectors)


def test_rotate2d_quarter_turn() -> None:
    vectors = np.array([[1.0, 0.0]])

    rotated = rotate2d(vectors, math.pi / 2)

    np.testing.assert_allclose(rotated, [[0.0, 1.0]], atol=1e-10)


def test_reanchor_trajectory_is_identity_when_pose_is_unchanged() -> None:
    relative_xy = np.array([[1.0, 0.0], [2.0, 0.1], [3.0, 0.3]])
    cached = CachedInference(
        anchor_time_us=0,
        origin_xy=np.array([10.0, 5.0]),
        origin_yaw=0.3,
        relative_xy=relative_xy,
    )

    reanchored = reanchor_trajectory(
        cached, current_xy=cached.origin_xy, current_yaw=cached.origin_yaw
    )

    np.testing.assert_allclose(reanchored, relative_xy, atol=1e-10)


def test_reanchor_trajectory_shrinks_gap_after_forward_translation() -> None:
    # Origin predicted a point 5m ahead (same yaw throughout). The ego has
    # since driven 2m forward - the same world point should now be only 3m
    # ahead in the (still straight-ahead) ego frame.
    relative_xy = np.array([[5.0, 0.0]])
    cached = CachedInference(
        anchor_time_us=0,
        origin_xy=np.array([0.0, 0.0]),
        origin_yaw=0.0,
        relative_xy=relative_xy,
    )

    reanchored = reanchor_trajectory(cached, current_xy=np.array([2.0, 0.0]), current_yaw=0.0)

    np.testing.assert_allclose(reanchored, [[3.0, 0.0]], atol=1e-10)


def test_reanchor_trajectory_accounts_for_ego_rotation() -> None:
    # A point straight ahead (5, 0) in the old ego frame, after the ego
    # turned 90 degrees left without moving, is now directly behind-right
    # in the new ego frame.
    relative_xy = np.array([[5.0, 0.0]])
    cached = CachedInference(
        anchor_time_us=0,
        origin_xy=np.array([0.0, 0.0]),
        origin_yaw=0.0,
        relative_xy=relative_xy,
    )

    reanchored = reanchor_trajectory(
        cached, current_xy=np.array([0.0, 0.0]), current_yaw=math.pi / 2
    )

    np.testing.assert_allclose(reanchored, [[0.0, -5.0]], atol=1e-10)


def _pose_namespace(x: float, y: float, yaw: float) -> SimpleNamespace:
    half = yaw / 2.0
    return SimpleNamespace(
        pose=SimpleNamespace(
            vec=SimpleNamespace(x=x, y=y, z=0.0),
            quat=SimpleNamespace(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half)),
        )
    )


def test_cache_context_extracts_session_time_and_pose() -> None:
    prediction_input = SimpleNamespace(
        session_uuid="session-1",
        time_now_us=1_000_000,
        ego_pose_history=[_pose_namespace(1.0, 2.0, 0.0), _pose_namespace(3.0, 4.0, math.pi / 2)],
    )

    session_uuid, time_now_us, current_xy, current_yaw = cache_context(prediction_input)

    assert session_uuid == "session-1"
    assert time_now_us == 1_000_000
    np.testing.assert_allclose(current_xy, [3.0, 4.0])
    assert current_yaw == pytest.approx(math.pi / 2)


def test_cache_context_disables_caching_without_session_uuid() -> None:
    prediction_input = SimpleNamespace(
        session_uuid=None,
        time_now_us=1_000_000,
        ego_pose_history=[_pose_namespace(1.0, 2.0, 0.0)],
    )

    assert cache_context(prediction_input) == (None, None, None, None)


def test_cache_context_disables_caching_without_pose_history() -> None:
    prediction_input = SimpleNamespace(
        session_uuid="session-1",
        time_now_us=1_000_000,
        ego_pose_history=[],
    )

    assert cache_context(prediction_input) == (None, None, None, None)


def _prediction_input(session_uuid: str, time_now_us: int, x: float, y: float, yaw: float) -> SimpleNamespace:
    return SimpleNamespace(
        session_uuid=session_uuid,
        time_now_us=time_now_us,
        ego_pose_history=[_pose_namespace(x, y, yaw)],
    )


def test_inference_cache_reuses_within_interval_and_refreshes_after() -> None:
    cache = PoseReanchoredInferenceCache(min_interval_s=0.5)
    calls = []

    def infer() -> np.ndarray:
        calls.append(1)
        return np.array([[5.0, 0.0]])

    # First call: no cache yet, must infer.
    _, reused0 = cache.get(_prediction_input("s", 0, 0.0, 0.0, 0.0), infer)
    assert reused0 is False
    assert len(calls) == 1

    # Still within min_interval_s: reuse.
    _, reused1 = cache.get(_prediction_input("s", 200_000, 1.0, 0.0, 0.0), infer)
    assert reused1 is True
    assert len(calls) == 1

    # Past min_interval_s: infer again.
    _, reused2 = cache.get(_prediction_input("s", 600_000, 2.0, 0.0, 0.0), infer)
    assert reused2 is False
    assert len(calls) == 2


def test_inference_cache_keys_are_isolated_per_session() -> None:
    cache = PoseReanchoredInferenceCache(min_interval_s=0.5)
    calls = []

    def infer() -> np.ndarray:
        calls.append(1)
        return np.array([[5.0, 0.0]])

    cache.get(_prediction_input("session-a", 0, 0.0, 0.0, 0.0), infer)
    cache.get(_prediction_input("session-b", 0, 0.0, 0.0, 0.0), infer)

    # Two distinct sessions each need their own first inference.
    assert len(calls) == 2


def test_inference_cache_always_infers_without_session_context() -> None:
    cache = PoseReanchoredInferenceCache(min_interval_s=0.5)
    calls = []

    def infer() -> np.ndarray:
        calls.append(1)
        return np.array([[5.0, 0.0]])

    prediction_input = SimpleNamespace(session_uuid=None, time_now_us=0, ego_pose_history=[])
    cache.get(prediction_input, infer)
    cache.get(prediction_input, infer)

    assert len(calls) == 2


def test_forget_evicts_a_session_so_it_no_longer_leaks_memory() -> None:
    cache = PoseReanchoredInferenceCache(min_interval_s=0.5)
    calls = []

    def infer() -> np.ndarray:
        calls.append(1)
        return np.array([[5.0, 0.0]])

    cache.get(_prediction_input("s", 0, 0.0, 0.0, 0.0), infer)
    assert "s" in cache._cache

    cache.forget("s")
    assert "s" not in cache._cache

    # Forgotten session must infer again, not reuse a phantom entry.
    _, reused = cache.get(_prediction_input("s", 200_000, 1.0, 0.0, 0.0), infer)
    assert reused is False
    assert len(calls) == 2


def test_forget_on_an_unknown_session_is_a_no_op() -> None:
    cache = PoseReanchoredInferenceCache(min_interval_s=0.5)
    cache.forget("never-registered")  # must not raise
