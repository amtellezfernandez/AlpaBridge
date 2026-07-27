# Proposed upstream PR: construct real CameraFrame instances in _prepare_camera_images

**Status:** drafted and fully verified against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened.

## Why

`CameraFrame` is declared as a typed `NamedTuple`:

```python
class CameraFrame(NamedTuple):
    """A single camera frame with timestamp."""
    timestamp_us: int
    image: np.ndarray  # HWC uint8 RGB


CameraImages = dict[str, list[CameraFrame]]
```

But `_prepare_camera_images` - the only place `CameraImages` values are actually constructed - builds plain positional tuples instead:

```python
camera_images[cam_id] = [(e.timestamp_us, e.image) for e in entries]
```

`CameraFrame` is never imported or referenced in `main.py` at all outside a docstring. So every `PredictionInput.camera_images` value a model ever receives is, at runtime, a plain `(timestamp_us, image)` tuple - not a real `CameraFrame` - even though the type declares otherwise. Code written against the documented type (`frame.timestamp_us`, `frame.image`) fails with `AttributeError` unless it falls back to positional indexing/unpacking. We hit this ourselves and it cost real debugging time to track down.

## The change

Construct real `CameraFrame` instances instead of plain tuples.

```diff
diff --git a/src/driver/src/alpasim_driver/main.py b/src/driver/src/alpasim_driver/main.py
--- a/src/driver/src/alpasim_driver/main.py
+++ b/src/driver/src/alpasim_driver/main.py
@@ -62,6 +62,7 @@
 from .models import DriveCommand
 from .models.base import (
     BaseTrajectoryModel,
+    CameraFrame,
     CameraImages,
     ModelInputValidationError,
     ModelPrediction,
@@ -646,7 +647,9 @@
         for cam_id in self._model.camera_ids:
             frame_cache = session.frame_caches[cam_id]
             entries = frame_cache.latest_frame_entries(self._context_length)
-            camera_images[cam_id] = [(e.timestamp_us, e.image) for e in entries]
+            camera_images[cam_id] = [
+                CameraFrame(timestamp_us=e.timestamp_us, image=e.image) for e in entries
+            ]
 
         return camera_images
```

## Verification performed

- `git apply --check` clean against a fresh clone of `main`.
- `py_compile` clean.
- `black --check` / `isort --check --profile black` clean.
- Checked every existing consumer of `camera_images` in the built-in models (`vam_model.py`, `manual_model.py`, `alpamayo_base.py`) - all three use positional unpacking (`latest_timestamp_us, latest_frame = frames[-1]`, `[img for _, img in frames]`), never attribute access. Since `NamedTuple` is a `tuple` subclass, positional unpacking and indexing behave identically whether the value is a plain tuple or a real `CameraFrame` - this change is purely additive (attribute access now also works) and doesn't risk breaking any existing consumer.
- Ran `_prepare_camera_images` directly (extracted via `ast`, real `CameraFrame`/`NamedTuple` semantics, fake frame cache) - confirmed the returned frames are real `CameraFrame` instances (`isinstance(frame, CameraFrame)` holds), attribute access (`frame.timestamp_us`) now works, and positional unpacking (`ts, img = frame`) still works exactly as before.
- Searched the driver test suite for anything asserting on the exact type/shape of `camera_images` entries - only reference is a full mock-out (`service._prepare_camera_images = lambda session: {}` in `test_inference_seeding.py`), not exercising the real implementation, so nothing to update.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b fix/camera-frame-type
git am third_party/alpasim_overrides/upstream-proposals/cameraframe-type-mismatch.patch  # patch is git-am-ready, own Subject/body
git push fork fix/camera-frame-type
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:fix/camera-frame-type \
  --title "driver: construct real CameraFrame instances instead of plain tuples" \
  --body-file <PR description derived from the "Why" section above>
```
