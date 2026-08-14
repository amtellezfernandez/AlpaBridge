"""Per-camera calibration carried from `start_session` to the policy.

AlpaSim hands the driver a calibration for every camera on the rig, and the
challenge contract is explicit that it must be used rather than hard-coded: the
supplied resolution describes the native camera and can differ from the JPEG
that actually arrives, so intrinsics have to be scaled to the delivered image
before any pixel-space calculation.

Nothing in the driver did that - the calibration was dropped on arrival - so a
policy reading pixels had to invent its own constants. This module keeps the
calibration and does the one transformation the contract requires.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

LOGGER = logging.getLogger("alpabridge_camera_calibration")

_PARAM_FIELDS = {
    "ftheta_param": "ftheta",
    "opencv_pinhole_param": "opencv_pinhole",
    "opencv_fisheye_param": "opencv_fisheye",
}


@dataclass(frozen=True)
class CameraCalibration:
    """Intrinsics for one camera, valid for `width` x `height` pixels.

    `width`/`height` are whatever the calibration currently describes: the
    declared resolution as received, or the delivered one after `scaled_to`.
    """

    logical_id: str
    width: int
    height: int
    model: str
    principal_point_x: float
    principal_point_y: float
    focal_length_x: float | None = None
    focal_length_y: float | None = None

    def scaled_to(self, width: int, height: int) -> "CameraCalibration":
        """Return this calibration expressed for a `width` x `height` image.

        Principal point and focal lengths are the terms that live in pixels, so
        they scale with the axis they belong to. Distortion coefficients are
        dimensionless and are deliberately not carried here.
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"cannot scale calibration to {width}x{height}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"calibration for {self.logical_id} declares an unusable "
                f"resolution {self.width}x{self.height}"
            )
        if (width, height) == (self.width, self.height):
            return self
        scale_x = width / self.width
        scale_y = height / self.height
        return replace(
            self,
            width=width,
            height=height,
            principal_point_x=self.principal_point_x * scale_x,
            principal_point_y=self.principal_point_y * scale_y,
            focal_length_x=(None if self.focal_length_x is None else self.focal_length_x * scale_x),
            focal_length_y=(None if self.focal_length_y is None else self.focal_length_y * scale_y),
        )


def _active_param(spec: Any) -> tuple[str, Any] | None:
    """Pick the populated entry of CameraSpec's `camera_param` oneof."""
    which = getattr(spec, "WhichOneof", None)
    if callable(which):
        field = which("camera_param")
        if field in _PARAM_FIELDS:
            return _PARAM_FIELDS[field], getattr(spec, field)
        return None
    # Test doubles carry a single attribute rather than a real oneof.
    for field, model in _PARAM_FIELDS.items():
        param = getattr(spec, field, None)
        if param is not None:
            return model, param
    return None


def calibration_from_available_camera(camera: Any) -> CameraCalibration | None:
    """Build a calibration from one `AvailableCamerasReturn.AvailableCamera`.

    Returns None when the message carries nothing usable, so a partial rig does
    not deny the policy the cameras that are fine.
    """
    spec = getattr(camera, "intrinsics", None)
    if spec is None:
        return None
    logical_id = str(getattr(spec, "logical_id", "") or getattr(camera, "logical_id", ""))
    if not logical_id:
        return None
    active = _active_param(spec)
    if active is None:
        LOGGER.warning("camera %s carries no recognised intrinsics model", logical_id)
        return None
    model, param = active
    width = int(getattr(spec, "resolution_w", 0) or 0)
    height = int(getattr(spec, "resolution_h", 0) or 0)
    if width <= 0 or height <= 0:
        LOGGER.warning(
            "camera %s declares resolution %sx%s; calibration cannot be scaled",
            logical_id,
            width,
            height,
        )
        return None
    focal_x = getattr(param, "focal_length_x", None)
    focal_y = getattr(param, "focal_length_y", None)
    return CameraCalibration(
        logical_id=logical_id,
        width=width,
        height=height,
        model=model,
        principal_point_x=float(getattr(param, "principal_point_x", 0.0) or 0.0),
        principal_point_y=float(getattr(param, "principal_point_y", 0.0) or 0.0),
        focal_length_x=None if focal_x is None else float(focal_x),
        focal_length_y=None if focal_y is None else float(focal_y),
    )


def camera_protos_from_session_request(request: Any) -> dict[str, Any]:
    """Keep the raw `AvailableCamera` messages, keyed by logical id.

    The parsed calibration is what a policy reasons with, but rectification is
    built from the original message: it needs the f-theta polynomial, which
    `CameraCalibration` deliberately does not carry.
    """
    spec = getattr(request, "rollout_spec", None)
    vehicle = getattr(spec, "vehicle", None) if spec is not None else None
    cameras = getattr(vehicle, "available_cameras", None) if vehicle is not None else None
    if not cameras:
        return {}
    protos: dict[str, Any] = {}
    for camera in cameras:
        intrinsics = getattr(camera, "intrinsics", None)
        logical_id = str(
            getattr(intrinsics, "logical_id", "") or getattr(camera, "logical_id", "")
        )
        if logical_id:
            protos[logical_id] = camera
    return protos


def calibrations_from_session_request(request: Any) -> dict[str, CameraCalibration]:
    """Collect every usable calibration from a `DriveSessionRequest`.

    An empty result is normal for the local baselines, which are served without
    a rollout spec; it is the pixel-reading policies that care.
    """
    spec = getattr(request, "rollout_spec", None)
    vehicle = getattr(spec, "vehicle", None) if spec is not None else None
    cameras = getattr(vehicle, "available_cameras", None) if vehicle is not None else None
    if not cameras:
        return {}
    calibrations: dict[str, CameraCalibration] = {}
    for camera in cameras:
        calibration = calibration_from_available_camera(camera)
        if calibration is not None:
            calibrations[calibration.logical_id] = calibration
    return calibrations
