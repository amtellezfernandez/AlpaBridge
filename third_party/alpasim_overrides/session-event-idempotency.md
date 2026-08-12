# Proposed upstream PR: treat late/duplicate session events as idempotent, not fatal

**Status:** re-cut 2026-08-12 from AlpaBridge's applied override; content verified by a live closed-loop rollout on `1e801ca` (198 frames, session COMPLETED, zero sensor failures). Applies cleanly to `main` @ `1e801ca`; not yet opened.

**Note on scope vs. the email to Max:** the email's bullet only named `close_session`/`submit_image_observation`/`submit_egomotion_observation`/`submit_route`. The patch also idempotently handles `drive` hitting an unknown session (currently `raise KeyError(...)`) - same category of fix, so it's included here as a fifth case rather than left out.

## Why

Right now, five `EgoDriverService` RPC handlers raise (`KeyError` or an unguarded `dict[...]` lookup that raises `KeyError` implicitly) when `request.session_uuid` isn't in `self._sessions`:

- `close_session` - raises if the session doesn't exist.
- `submit_image_observation` - unguarded `self._sessions[request.session_uuid]`.
- `submit_egomotion_observation` - unguarded `self._sessions[request.session_uuid]`.
- `submit_route` - unguarded `self._sessions[request.session_uuid]` (twice, once per branch).
- `drive` - raises if the session doesn't exist.

In a live rollout, requests for a session that's already closed (a duplicate `close_session`, or an observation that arrives just after teardown) are a normal race, not a client error - the request is late, not wrong. Right now that race turns into an unhandled `KeyError` propagating out of the RPC handler.

## The change

Each of the five handlers gets the same shape: look the session up with `.get(...)` (or check membership first for the two that raise directly), and if it's missing, log a warning and return the same "nothing to do" response the RPC would return on success (`Empty()` for the four fire-and-forget RPCs, an empty-trajectory `DriveResponse` for `drive`) instead of raising.

```diff
diff --git a/src/driver/src/alpasim_driver/main.py b/src/driver/src/alpasim_driver/main.py
--- a/src/driver/src/alpasim_driver/main.py
+++ b/src/driver/src/alpasim_driver/main.py
@@ -747,7 +747,11 @@
         self, request: DriveSessionCloseRequest, context: grpc.aio.ServicerContext
     ) -> Empty:
         if request.session_uuid not in self._sessions:
-            raise KeyError(f"Session {request.session_uuid} does not exist.")
+            logger.warning(
+                "close_session for unknown session %s; treating as idempotent",
+                request.session_uuid,
+            )
+            return Empty()
 
         logger.info(f"Closing session {request.session_uuid}")
         del self._sessions[request.session_uuid]
@@ -771,7 +775,14 @@
     ) -> Empty:
         grpc_image = request.camera_image
         image = Image.open(BytesIO(grpc_image.image_bytes))
-        session = self._sessions[request.session_uuid]
+        session = self._sessions.get(request.session_uuid)
+        if session is None:
+            logger.warning(
+                "submit_image_observation for unknown session %s at %s; ignoring late frame",
+                request.session_uuid,
+                grpc_image.frame_end_us,
+            )
+            return Empty()
         if grpc_image.logical_id not in session.desired_cameras_logical_ids:
             raise ValueError(f"Camera {grpc_image.logical_id} not in desired cameras")
 
@@ -795,7 +806,19 @@
     async def submit_egomotion_observation(
         self, request: RolloutEgoTrajectory, context: grpc.aio.ServicerContext
     ) -> Empty:
-        session = self._sessions[request.session_uuid]
+        session = self._sessions.get(request.session_uuid)
+        if session is None:
+            last_ts = (
+                request.trajectory.poses[-1].timestamp_us
+                if request.trajectory.poses
+                else "unknown"
+            )
+            logger.warning(
+                "submit_egomotion_observation for unknown session %s at %s; ignoring late egomotion",
+                request.session_uuid,
+                last_ts,
+            )
+            return Empty()
 
         session.add_egoposes(request.trajectory)
 
@@ -813,15 +836,22 @@
         self, request: RouteRequest, context: grpc.aio.ServicerContext
     ) -> Empty:
         logger.debug("submit_route: waypoint count=%s", len(request.route.waypoints))
+        session = self._sessions.get(request.session_uuid)
+        if session is None:
+            logger.warning(
+                "submit_route for unknown session %s; ignoring late route update",
+                request.session_uuid,
+            )
+            return Empty()
         if self._cfg.route is not None:
-            self._sessions[request.session_uuid].update_command_from_route(
+            session.update_command_from_route(
                 request.route,
                 self._cfg.route.use_waypoint_commands,
                 self._cfg.route.command_distance_threshold,
                 self._cfg.route.min_lookahead_distance,
             )
         else:
-            self._sessions[request.session_uuid].update_command_from_route(
+            session.update_command_from_route(
                 request.route,
                 use_waypoint_commands=False,
             )
@@ -843,7 +873,12 @@
         self, request: DriveRequest, context: grpc.aio.ServicerContext
     ) -> DriveResponse:
         if request.session_uuid not in self._sessions:
-            raise KeyError(f"Session {request.session_uuid} not found")
+            logger.warning(
+                "drive for unknown session %s at %s; returning empty trajectory",
+                request.session_uuid,
+                request.time_query_us,
+            )
+            return DriveResponse(trajectory=Trajectory())
 
         session = self._sessions[request.session_uuid]
```

## Verification performed

- `git apply --check` clean against a fresh clone of `main` (commit `3032e0c`).
- `py_compile` clean.
- `black --check` clean.
- `isort --check --profile black` clean, run from within the cloned repo (isort's first-party detection depends on directory context - run in isolation on just the file, it misclassifies `import grpc`/`grpc.aio`, but that's a pre-existing property of the whole file, unrelated to this diff, confirmed by checking the pristine file the same way).
- No existing test in the driver test suite asserts the old raising behavior for any of these five RPCs (searched for `KeyError`/`does not exist`/`not found` across `tests/*.py` - no hits).
- `test_service_flow.py`'s existing happy-path test calls all four of `submit_egomotion_observation`/`submit_image_observation`/`submit_route`/`drive` against a session it just created - always a valid, existing session, so it exercises the unchanged success path, not the new branch.
- Extracted all five methods via `ast` and ran each directly against a real, unknown `session_uuid` with real compiled protobuf request types (`DriveSessionCloseRequest`, `RolloutCameraImage` with a real encoded PNG payload, `RolloutEgoTrajectory`, `RouteRequest`, `DriveRequest`) - all five return their "nothing to do" response and log a warning, none raise.

## How to open this, once approved

Same process as PR #127 and the route-waypoints proposal:

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b fix/idempotent-session-events
git am third_party/alpasim_overrides/session-event-idempotency.patch  # patch is git-am-ready, own Subject/body
git push fork fix/idempotent-session-events
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:fix/idempotent-session-events \
  --title "driver: treat late/duplicate session events as idempotent, not fatal" \
  --body-file <PR description derived from the "Why" section above>
```
