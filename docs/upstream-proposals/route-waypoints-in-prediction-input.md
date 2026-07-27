# Proposed upstream PR: forward route waypoints (and session identifiers) into PredictionInput

**Status:** drafted and fully verified against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened. Waiting on confirmation from the Max/AlpaSim discussion before filing.

Related, already-open items for context:

- [PR #127](https://github.com/NVlabs/alpasim/pull/127) - `_get_speed_and_acceleration` fallback fix (merged discussion, precedent for how this one should be verified/formatted).
- [Issue #128](https://github.com/NVlabs/alpasim/issues/128) - rollout seed reproducibility question.
- This proposal is the concrete, PR-ready version of the `route_waypoints.patch`/`RouteGenerator` discussion from the AlpaSim maintainer thread.

## Why

`EgoDriverService.update_command_from_route` reduces a full route down to a derived `DriveCommand` (LEFT/STRAIGHT/RIGHT) and discards the actual waypoint geometry before `PredictionInput` is built. A route-following policy that reasons over geometry rather than a coarse command has no way to get at that data - it's already present in the driver (received via `submit_route`), just never forwarded.

Concretely: with real route waypoints, a route-following model follows the road; with only the derived command, it can't distinguish a straight road from a bend, and falls back to a naive straight-line prediction. A controlled check (same model, same speed, same starting pose, one prediction step, a road curving left ~20m out) showed the two predicted paths diverging to 14m apart by the end of a 5-second horizon.

Two more small, related gaps get closed the same way: there's currently no way for a driver plugin to know which session or scene a `PredictionInput` came from (useful for per-session telemetry/logging), even though the driver already tracks both (`Session.uuid`, `Session.debug_scene_id`).

## What this does *not* do

This does not make `RouteGenerator` pluggable (see the separate discussion about `alpasim.route_generators` as an entry-point group, mirroring `alpasim.models`). That's a runtime-side change (how a route is computed) and is orthogonal to this PR, which is entirely driver-side (how an already-computed route is forwarded to `PredictionInput`). The two are complementary but independent - this PR is useful regardless of whether `RouteGenerator` ever becomes pluggable.

It also deliberately does *not* add a raw `runtime_random_seed` field. `inference_seed` (`session.seed + inference_count`) already gives models something seed-derived for determinism; a second, separate raw-seed field wasn't as clearly motivated as `route_waypoints`/`session_uuid`/`debug_scene_id`, so it's left out to keep the diff minimal and easy to justify.

## The change

Three fields added to `Session` / `PredictionInput`, all backward compatible (appended at the end, all default to `None`, so existing positional or keyword construction is unaffected):

```python
# Session
current_route: Route | None = None

def route_waypoints_for_prediction(self) -> list[Vec3] | None:
    """Return the latest route waypoints in the current rig frame."""
    if self.current_route is None:
        return None
    return list(self.current_route.waypoints)

# PredictionInput
route_waypoints: list[Any] | None = None  # list[Vec3] in current rig frame
session_uuid: str | None = None
debug_scene_id: str | None = None
```

The route is captured in `update_command_from_route` *before* its existing early return (`if not use_waypoint_commands or len(route.waypoints) < 1: return`), so it's available even when `use_waypoint_commands=False` - the case that matters most for a route-following policy that wants full geometry rather than a derived command.

Full diff (verified to apply cleanly against current `main`, see Verification below):

```diff
diff --git a/src/driver/src/alpasim_driver/main.py b/src/driver/src/alpasim_driver/main.py
--- a/src/driver/src/alpasim_driver/main.py
+++ b/src/driver/src/alpasim_driver/main.py
@@ -157,6 +157,7 @@
     dynamic_states: list[tuple[int, DynamicState]] = field(default_factory=list)
     current_command: DriveCommand = DriveCommand.STRAIGHT  # Default to straight
     inference_count: int = 0
+    current_route: Route | None = None
 
     @staticmethod
     def create(
@@ -360,6 +361,9 @@
             min_lookahead_distance: Minimum forward distance (meters) to consider
                 a waypoint as the target for command derivation.
         """
+        self.current_route = Route()
+        self.current_route.CopyFrom(route)
+
         if not use_waypoint_commands or len(route.waypoints) < 1:
             return
 
@@ -384,6 +388,13 @@
             self.current_command.name,
         )
 
+    def route_waypoints_for_prediction(self) -> list[Vec3] | None:
+        """Return the latest route waypoints in the current rig frame."""
+
+        if self.current_route is None:
+            return None
+        return list(self.current_route.waypoints)
+
 
 def async_log_call(func: Callable) -> Callable:
     """Helper to add logging for gRPC calls (sync or async)."""
@@ -712,6 +723,9 @@
                     acceleration=acceleration,
                     ego_pose_history=job.session.poses,
                     inference_seed=inference_seed,
+                    route_waypoints=job.session.route_waypoints_for_prediction(),
+                    session_uuid=job.session.uuid,
+                    debug_scene_id=job.session.debug_scene_id,
                 )
             )
         return self._model.predict_batch(inputs)
diff --git a/src/driver/src/alpasim_driver/models/base.py b/src/driver/src/alpasim_driver/models/base.py
--- a/src/driver/src/alpasim_driver/models/base.py
+++ b/src/driver/src/alpasim_driver/models/base.py
@@ -54,6 +54,9 @@
     acceleration: float  # m/s²
     ego_pose_history: list[Any]  # list[PoseAtTime]
     inference_seed: int  # Session seed plus the zero-based inference count
+    route_waypoints: list[Any] | None = None  # list[Vec3] in current rig frame
+    session_uuid: str | None = None
+    debug_scene_id: str | None = None
 
 
 @dataclass
diff --git a/src/driver/src/alpasim_driver/tests/test_inference_seeding.py b/src/driver/src/alpasim_driver/tests/test_inference_seeding.py
--- a/src/driver/src/alpasim_driver/tests/test_inference_seeding.py
+++ b/src/driver/src/alpasim_driver/tests/test_inference_seeding.py
@@ -38,7 +38,14 @@
     service._model = _CapturingModel()
     service._get_speed_and_acceleration = lambda session: (0.0, 0.0)
     service._prepare_camera_images = lambda session: {}
-    session = SimpleNamespace(seed=123, inference_count=0, poses=[])
+    session = SimpleNamespace(
+        seed=123,
+        inference_count=0,
+        poses=[],
+        uuid="session",
+        debug_scene_id=None,
+        route_waypoints_for_prediction=lambda: None,
+    )
 
     service._run_batch([_drive_job(session)])
     service._run_batch([_drive_job(session)])
```

## Verification performed

All done against a fresh clone of `NVlabs/alpasim` `main` (commit `3032e0c`), not just the patch file in isolation:

- `git apply --check` clean against current `main`.
- `black --check` / `isort --check --profile black` clean on all three touched files, per their `CONTRIBUTING.md`.
- `py_compile` clean on `main.py` and `models/base.py`.
- Confirmed `Route`/`Vec3` are already imported in `main.py` - no new imports needed.
- Confirmed via `egodriver.proto:25`'s own docstring ("Waypoints for a route expressed in the rig frame") that `route_waypoints_for_prediction()`'s frame claim matches their own documented contract, not an assumption.
- Extracted `Session.update_command_from_route`/`route_waypoints_for_prediction` via `ast` and ran them against real compiled protobuf types (`Route`, `Vec3`):
  - Before any route is submitted, `route_waypoints_for_prediction()` returns `None`.
  - After submitting a route with `use_waypoint_commands=False` (the early-return path), the route is still captured and returned correctly - this is the path that matters most.
- Verified `PredictionInput` backward compatibility directly against the real (patched) module: existing 6-field construction (no new kwargs) still works, all three new fields default to `None`; construction with the new fields also works.
- **Found and fixed a real regression before considering this final:** the existing test `test_run_batch_assigns_consecutive_per_session_inference_seeds` (`test_inference_seeding.py`) mocks `session` as a minimal `SimpleNamespace(seed=123, inference_count=0, poses=[])`. The patched `_run_batch` calls `job.session.uuid`, `.debug_scene_id`, and `.route_waypoints_for_prediction()`, none of which that mock has. Proved this by extracting `_run_batch` via `ast` and running it against the exact existing mock - `AttributeError`. Fixed by extending that one mock (included in the diff above); re-verified the test's real assertions (the `[123, 124]` inference-seed sequence) still pass against the extracted method.
- Swept the rest of the driver test suite for other minimal session mocks of this shape - this was the only one.
- Checked `test_vam_batched.py`'s `PredictionInput(...)` construction (old 6-field form, no new kwargs) - unaffected.

## How to actually open this, once approved

Same process as PR #127:

```bash
gh repo fork NVlabs/alpasim --remote=false   # already forked as amtellezfernandez/alpasim
cd <a clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b feat/route-waypoints-in-prediction-input
git am docs/upstream-proposals/route-waypoints-in-prediction-input.patch  # patch is git-am-ready, own Subject/body
git push fork feat/route-waypoints-in-prediction-input
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:feat/route-waypoints-in-prediction-input \
  --title "driver: forward route waypoints and session identifiers into PredictionInput" \
  --body-file <PR description derived from the "Why" section above>
```
