# Proposed upstream PR: lazy-import optional model backends in models/__init__.py

**Status:** drafted and fully verified against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened.

## Why

`alpasim_driver.models.__init__` eagerly imports all four model backends at package-import time:

```python
from .alpamayo1_5_model import Alpamayo15Model
from .alpamayo1_model import Alpamayo1Model
...
from .vam_model import VAMModel
```

`Alpamayo1Model`, `Alpamayo15Model`, and `VAMModel` each depend on proprietary, non-public packages (`alpamayo_r1`, `alpamayo1_5`, `vam` respectively - none of these are on public PyPI). That means simply `import alpasim_driver.models` fails entirely for anyone who has only one of those backends installed (or none at all, e.g. a route-following or manual-control setup that doesn't need any learned model) - the package can't even be imported to get at `BaseTrajectoryModel`/`PredictionInput`/`ManualModel`, which don't need any of those.

This matters more as more third-party model plugins show up: registering one plugin's entry point shouldn't require every other model's dependency stack to be installed just to import the shared base module.

## The change

Move the three proprietary-backend imports behind `__getattr__` (PEP 562 lazy module attributes), keeping `ManualModel` (only depends on the public `pygame` package) and `base` (no optional deps at all) eager.

```diff
diff --git a/src/driver/src/alpasim_driver/models/__init__.py b/src/driver/src/alpasim_driver/models/__init__.py
--- a/src/driver/src/alpasim_driver/models/__init__.py
+++ b/src/driver/src/alpasim_driver/models/__init__.py
@@ -1,10 +1,19 @@
 # SPDX-License-Identifier: Apache-2.0
 # Copyright (c) 2025-2026 NVIDIA Corporation
 
-"""Model abstraction layer for trajectory prediction models."""
+"""Model abstraction layer for trajectory prediction models.
+
+This override keeps the base abstractions importable in minimal local-driver
+environments where heavyweight built-in backends (VAM/Alpamayo) are not
+installed. Those backends remain available through their entry points when
+their optional dependencies are present.
+"""
+
+from __future__ import annotations
+
+from importlib import import_module
+from typing import Any
 
-from .alpamayo1_5_model import Alpamayo15Model
-from .alpamayo1_model import Alpamayo1Model
 from .base import (
     BaseTrajectoryModel,
     CameraFrame,
@@ -14,7 +23,12 @@ from .base import (
     PredictionInput,
 )
 from .manual_model import ManualModel
-from .vam_model import VAMModel
+
+_LAZY_IMPORTS = {
+    "Alpamayo15Model": ".alpamayo1_5_model",
+    "Alpamayo1Model": ".alpamayo1_model",
+    "VAMModel": ".vam_model",
+}
 
 __all__ = [
     "Alpamayo15Model",
@@ -28,3 +42,13 @@ __all__ = [
     "PredictionInput",
     "VAMModel",
 ]
+
+
+def __getattr__(name: str) -> Any:
+    module_name = _LAZY_IMPORTS.get(name)
+    if module_name is None:
+        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
+    module = import_module(module_name, __name__)
+    value = getattr(module, name)
+    globals()[name] = value
+    return value
```

`ManualModel` stays eager rather than joining `_LAZY_IMPORTS`: it only imports `pygame`, a normal public package, not a gated one - there's no availability problem to defer.

## Verification performed

Ran directly, not just reasoned about - installed the one missing *public* dependency (`pygame`, needed by `ManualModel`) so the comparison isolates exactly the proprietary-package problem this PR solves:

```
=== PRISTINE (unpatched) models/__init__.py ===
ModuleNotFoundError: No module named 'alpamayo1_5'
(import alpasim_driver.models fails completely)

=== PATCHED (lazy imports) models/__init__.py ===
import succeeded: ['Alpamayo15Model', 'Alpamayo1Model', 'BaseTrajectoryModel', 'CameraFrame',
                    'CameraImages', 'DriveCommand', 'ManualModel', 'ModelPrediction',
                    'PredictionInput', 'VAMModel']
base classes accessible: BaseTrajectoryModel, ManualModel
Accessing Alpamayo1Model correctly defers and fails only now: No module named 'alpamayo_r1'
```

So: the package now imports successfully with none of the three proprietary backends installed, `BaseTrajectoryModel`/`ManualModel`/`PredictionInput`/etc. are usable immediately, and the `ModuleNotFoundError` for an actually-missing backend is deferred to the point of use rather than blocking the whole package - which is the intended behavior, not silently swallowed (accessing `Alpamayo1Model` without `alpamayo_r1` installed still raises, just later and more precisely, naming the specific missing backend rather than failing on whichever backend happened to be imported first).

Also checked:
- `git apply --check` clean against a fresh clone of `main`.
- `py_compile` clean.
- `black --check` / `isort --check --profile black` clean.
- Confirmed all three lazily-loaded backends genuinely depend on non-public packages (`alpamayo_r1`, `alpamayo1_5`, `vam` - none resolvable via `pip install`), while `manual_model.py`'s only unusual dependency (`pygame`) is ordinary and publicly installable - this is why it's excluded from `_LAZY_IMPORTS`, not an oversight.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b feat/lazy-model-imports
git am third_party/alpasim_overrides/upstream-proposals/lazy-model-imports.patch  # patch is git-am-ready, own Subject/body
git push fork feat/lazy-model-imports
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:feat/lazy-model-imports \
  --title "driver: lazily import optional model backends in models/__init__.py" \
  --body-file <PR description derived from the "Why" section above>
```
