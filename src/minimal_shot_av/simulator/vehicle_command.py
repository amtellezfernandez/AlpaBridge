from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any, Sequence

from .policy import StepRecord
from .safety import SafeAction


@dataclass(frozen=True)
class VehicleCommandLimits:
    max_speed_mps: float = 2.0
    max_abs_steering_rad: float = 0.6
    max_abs_accel_mps2: float = 1.0


@dataclass(frozen=True)
class ValidationContext:
    safety_driver_present: bool = True
    geofence_ok: bool = True
    shadow_mode: bool = True
    manual_takeover_available: bool = True
    remote_estop_available: bool = True
    physical_estop_available: bool = True


@dataclass(frozen=True)
class VehicleCommand:
    timestamp_s: float
    mode: str
    steering_rad: float
    speed_mps: float
    accel_mps2: float
    brake: float
    source: str
    estop_required: bool
    geofence_ok: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def command_from_safe_action(
    action: SafeAction,
    *,
    timestamp_s: float,
    previous_speed_mps: float = 0.0,
    dt_s: float = 0.25,
    source: str = "spotlight_reflex",
) -> VehicleCommand:
    steering = math.atan2(action.direction[1], action.direction[0]) if action.direction != (0.0, 0.0) else 0.0
    accel = (float(action.speed) - float(previous_speed_mps)) / max(dt_s, 1e-6)
    return VehicleCommand(
        timestamp_s=float(timestamp_s),
        mode=action.mode,
        steering_rad=float(steering),
        speed_mps=float(action.speed),
        accel_mps2=float(accel),
        brake=1.0 if action.speed <= 1e-9 else 0.0,
        source=source,
        estop_required=False,
        geofence_ok=True,
        reason="from_safe_action",
    )


def commands_from_rollout_steps(
    steps: Sequence[StepRecord],
    *,
    source: str = "spotlight_reflex",
    dt_s: float = 0.25,
) -> list[VehicleCommand]:
    commands: list[VehicleCommand] = []
    previous_speed = 0.0
    previous_xy: tuple[float, float] | None = None
    for step in steps:
        if previous_xy is None:
            steering = 0.0
        else:
            dx = step.x - previous_xy[0]
            dy = step.y - previous_xy[1]
            steering = math.atan2(dy, dx) if (dx, dy) != (0.0, 0.0) else 0.0
        accel = (float(step.speed) - previous_speed) / max(dt_s, 1e-6)
        commands.append(
            VehicleCommand(
                timestamp_s=float(step.t) * dt_s,
                mode=step.action_mode,
                steering_rad=float(steering),
                speed_mps=float(step.speed),
                accel_mps2=float(accel),
                brake=1.0 if step.speed <= 1e-9 else 0.0,
                source=source,
                estop_required=False,
                geofence_ok=True,
                reason="from_rollout_step",
            )
        )
        previous_speed = float(step.speed)
        previous_xy = (float(step.x), float(step.y))
    return commands


def apply_command_envelope(
    command: VehicleCommand,
    *,
    limits: VehicleCommandLimits | None = None,
    context: ValidationContext | None = None,
) -> VehicleCommand:
    limits = limits or VehicleCommandLimits()
    context = context or ValidationContext()
    rejection = _rejection_reason(command, context)
    if rejection:
        return _stopped_command(command, reason=rejection, estop_required=True, geofence_ok=context.geofence_ok)

    steering = _clamp(command.steering_rad, -limits.max_abs_steering_rad, limits.max_abs_steering_rad)
    speed = _clamp(command.speed_mps, 0.0, limits.max_speed_mps)
    accel = _clamp(command.accel_mps2, -limits.max_abs_accel_mps2, limits.max_abs_accel_mps2)
    reasons: list[str] = []
    if steering != command.steering_rad:
        reasons.append("steering_clamped")
    if speed != command.speed_mps:
        reasons.append("speed_clamped")
    if accel != command.accel_mps2:
        reasons.append("accel_clamped")
    return replace(
        command,
        steering_rad=steering,
        speed_mps=speed,
        accel_mps2=accel,
        brake=1.0 if speed <= 1e-9 else max(0.0, min(1.0, command.brake)),
        geofence_ok=context.geofence_ok,
        reason=",".join(reasons) if reasons else command.reason,
    )


def command_violations(
    command: VehicleCommand,
    *,
    limits: VehicleCommandLimits | None = None,
) -> list[str]:
    limits = limits or VehicleCommandLimits()
    violations: list[str] = []
    numeric_fields = {
        "timestamp_s": command.timestamp_s,
        "steering_rad": command.steering_rad,
        "speed_mps": command.speed_mps,
        "accel_mps2": command.accel_mps2,
        "brake": command.brake,
    }
    for name, value in numeric_fields.items():
        if not math.isfinite(value):
            violations.append(f"{name}_not_finite")
    if command.speed_mps < -1e-9 or command.speed_mps > limits.max_speed_mps + 1e-9:
        violations.append("speed_out_of_bounds")
    if abs(command.steering_rad) > limits.max_abs_steering_rad + 1e-9:
        violations.append("steering_out_of_bounds")
    if abs(command.accel_mps2) > limits.max_abs_accel_mps2 + 1e-9:
        violations.append("accel_out_of_bounds")
    if not 0.0 <= command.brake <= 1.0:
        violations.append("brake_out_of_bounds")
    if not command.geofence_ok:
        violations.append("geofence_not_ok")
    if command.estop_required and command.speed_mps > 1e-9:
        violations.append("estop_with_motion")
    return violations


def command_report(
    commands: Sequence[VehicleCommand],
    *,
    limits: VehicleCommandLimits | None = None,
    shadow_mode_only: bool = True,
    estop_tested: bool = False,
    manual_takeover_tested: bool = False,
    geofence_tested: bool = False,
) -> dict[str, Any]:
    limits = limits or VehicleCommandLimits()
    violations: list[dict[str, Any]] = []
    max_speed = 0.0
    max_abs_steering = 0.0
    clamped = 0
    rejected = 0
    for index, command in enumerate(commands):
        command_issues = command_violations(command, limits=limits)
        if command_issues:
            violations.append({"index": index, "violations": command_issues, "command": command.to_dict()})
        max_speed = max(max_speed, abs(command.speed_mps))
        max_abs_steering = max(max_abs_steering, abs(command.steering_rad))
        if "clamped" in command.reason:
            clamped += 1
        if command.estop_required:
            rejected += 1
    return {
        "schema": "vehicle_validation_shadow_report_v1",
        "command_count": len(commands),
        "violations": violations,
        "violation_count": len(violations),
        "clamped_command_count": clamped,
        "rejected_command_count": rejected,
        "max_speed_mps": round(max_speed, 6),
        "max_abs_steering_rad": round(max_abs_steering, 6),
        "estop_tested": bool(estop_tested),
        "manual_takeover_tested": bool(manual_takeover_tested),
        "geofence_tested": bool(geofence_tested),
        "shadow_mode_only": bool(shadow_mode_only),
        "ready_for_low_speed_actuation": (
            bool(commands)
            and not violations
            and bool(shadow_mode_only)
            and bool(estop_tested)
            and bool(manual_takeover_tested)
            and bool(geofence_tested)
        ),
    }


def _rejection_reason(command: VehicleCommand, context: ValidationContext) -> str:
    if any(
        not math.isfinite(value)
        for value in (command.timestamp_s, command.steering_rad, command.speed_mps, command.accel_mps2, command.brake)
    ):
        return "invalid_numeric_command"
    if command.estop_required:
        return "estop_required"
    if not context.geofence_ok:
        return "geofence_not_ok"
    if not context.safety_driver_present:
        return "missing_safety_driver"
    if not context.manual_takeover_available:
        return "manual_takeover_unavailable"
    if not context.remote_estop_available or not context.physical_estop_available:
        return "estop_unavailable"
    if not context.shadow_mode:
        return "actuation_without_shadow_approval"
    return ""


def _stopped_command(
    command: VehicleCommand,
    *,
    reason: str,
    estop_required: bool,
    geofence_ok: bool,
) -> VehicleCommand:
    return replace(
        command,
        steering_rad=0.0,
        speed_mps=0.0,
        accel_mps2=0.0,
        brake=1.0,
        estop_required=estop_required,
        geofence_ok=geofence_ok,
        reason=reason,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))
