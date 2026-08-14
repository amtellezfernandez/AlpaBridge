"""Rectify f-theta rig frames into the pinhole view a policy expects.

The rig's 120 degree cameras are f-theta and place their optical centre about
200 px below the frame centre; models like VAVAM were trained on rectified,
roughly centred pinhole images. Feeding one the other is a silent domain gap
that no amount of cropping fixes.

The transform itself is AlpaSim's, vendored verbatim under
`alpabridge/third_party/` so it matches the reference submission exactly. This
module is the AlpaBridge side: when to build a rectifier, what to do when the
optional dependencies are missing, and never failing a rollout over it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

LOGGER = logging.getLogger("alpabridge_camera_rectification")

_WARNED: set[str] = set()

# The reference submission's NuScenes-style pinhole target. Reproduced from
# `default_rectification_config()` in AlpaSim's sample_submission_vavam driver
# so a rectified frame here matches a rectified frame there.
_TARGET_FOCAL_LENGTH = (1545.0, 1545.0)
_TARGET_PRINCIPAL_POINT = (960.0, 560.0)
_TARGET_RESOLUTION_HW = (1080, 1920)
_TARGET_RADIAL = (-0.356123, 0.172545, -0.05231, 0.0, 0.0, 0.0)
_TARGET_TANGENTIAL = (-0.00213, 0.000464)
_TARGET_THIN_PRISM = (0.0, 0.0, 0.0, 0.0)


def _warn_once(key: str, message: str) -> None:
    if key not in _WARNED:
        _WARNED.add(key)
        LOGGER.warning(message)


def rectification_disabled() -> bool:
    """True when the operator has opted out of rectification."""
    raw = os.environ.get("ALPABRIDGE_DISABLE_RECTIFICATION", "0").strip().lower()
    return raw in {"1", "true", "yes"}


def default_target_config() -> Any:
    """The pinhole target to rectify into, or None if the transform is absent."""
    try:
        from alpabridge.third_party.alpasim_rectification import (
            RectificationTargetConfig,
        )
    except ImportError as exc:
        _warn_once(
            "rectification-unavailable",
            "Camera rectification is unavailable, so f-theta frames reach policies "
            f"as rendered: {exc}. Install alpabridge[rectify] for the decoder and "
            "have alpasim_grpc importable.",
        )
        return None
    return RectificationTargetConfig(
        focal_length=_TARGET_FOCAL_LENGTH,
        principal_point=_TARGET_PRINCIPAL_POINT,
        resolution_hw=_TARGET_RESOLUTION_HW,
        radial=_TARGET_RADIAL,
        tangential=_TARGET_TANGENTIAL,
        thin_prism=_TARGET_THIN_PRISM,
    )


def build_rectifier(camera_proto: Any, source_hw: tuple[int, int]) -> Any | None:
    """Build a rectifier for one camera at the resolution actually delivered.

    Returns None whenever rectification cannot be done, having said why once:
    a rollout that runs unrectified is worse than one that runs, but a rollout
    that dies on a missing optional dependency is worse than both.
    """
    if camera_proto is None:
        return None
    target = default_target_config()
    if target is None:
        return None
    try:
        from alpabridge.third_party.alpasim_rectification import (
            build_ftheta_rectifier_for_resolution,
        )

        return build_ftheta_rectifier_for_resolution(camera_proto, target, source_hw)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        _warn_once(
            f"rectifier-build-failed-{source_hw}",
            f"Could not build a rectifier for a {source_hw[1]}x{source_hw[0]} frame; "
            f"passing it through unrectified: {exc!r}",
        )
        return None


def rectify_image(rectifier: Any, image: np.ndarray) -> np.ndarray:
    """Apply `rectifier`, falling back to the original frame on any failure."""
    if rectifier is None:
        return image
    try:
        return np.asarray(rectifier.rectify(image))
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        _warn_once(
            "rectify-failed",
            f"Rectifying a camera frame failed; using it as rendered: {exc!r}",
        )
        return image
