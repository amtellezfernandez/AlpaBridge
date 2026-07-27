# Proposed upstream PR: make RouteGenerator selectable via the existing plugin registry

**Status:** drafted and fully verified against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened.

**Related:** this is the runtime-side half of the route discussion with Max. It's independent of, and complementary to, the [route-waypoints-in-PredictionInput proposal](./route-waypoints-in-prediction-input.md) - that one is about the driver forwarding a route it already has; this one is about letting the runtime source that route from somewhere other than the two built-in generators. Neither depends on the other.

## Why

`RouteGeneratorType` (`RECORDED`/`MAP`/`NONE`) is a closed `Enum`, and `RouteGenerator.create()` dispatches to one of two hardcoded subclasses based on it. There's no way to plug in a custom route source (e.g. an external routing service, a different map format, a hand-authored scenario route) without editing this file directly.

Meanwhile, the codebase already has a generic, established mechanism for exactly this kind of extensibility - `PluginRegistry`, an entry-point-based registry already used for four other extension points:

```python
# src/plugins/alpasim_plugins/plugins.py
models = PluginRegistry("alpasim.models")
mpc_controllers = PluginRegistry("alpasim.mpc")
scorers = PluginRegistry("alpasim.scorers")
tools = PluginRegistry("alpasim.tools")
```

`alpasim.models` in particular is the more complete version of this idea: all four built-in driver models (`Alpamayo1Model`, `Alpamayo15Model`, `VAMModel`, `ManualModel`) are themselves registered through it (`src/driver/pyproject.toml`'s `[project.entry-points."alpasim.models"]`), with zero special-casing in `main.py` - `model_registry.get(cfg.model_type).from_config(...)` handles all of them uniformly.

## Scope decision worth being explicit about

Fully mirroring the models pattern would mean migrating `RouteGeneratorRecorded`/`RouteGeneratorMap` to also be registered entry points and removing the enum/if-elif dispatch entirely. We deliberately did **not** do that here: `RouteGenerator` is an `ABC`, and Python requires every concrete subclass to implement any abstract method added to it - retrofitting a uniform construction contract would mean also touching both existing built-in classes, which is a bigger, riskier change than this proposal aims to be. Instead, this adds a strictly additive opt-in: a new `route_generator_plugin: str | None` field that, when set, resolves the generator through the registry instead of the enum; when unset (the default), the existing dispatch is completely untouched. A follow-up could pursue the fuller unification later if that's wanted.

## The change

```diff
diff --git a/src/plugins/alpasim_plugins/plugins.py b/src/plugins/alpasim_plugins/plugins.py
--- a/src/plugins/alpasim_plugins/plugins.py
+++ b/src/plugins/alpasim_plugins/plugins.py
@@ -107,6 +107,7 @@
 mpc_controllers = PluginRegistry("alpasim.mpc")
 scorers = PluginRegistry("alpasim.scorers")
 tools = PluginRegistry("alpasim.tools")
+route_generators = PluginRegistry("alpasim.route_generators")
 
 
 def get_plugin_info() -> dict[str, list[str]]:
@@ -121,5 +122,6 @@
         "alpasim.scorers",
         "alpasim.tools",
         "alpasim.configs",
+        "alpasim.route_generators",
     ]
     return {group: PluginRegistry(group).get_names() for group in groups}
diff --git a/src/runtime/alpasim_runtime/config.py b/src/runtime/alpasim_runtime/config.py
--- a/src/runtime/alpasim_runtime/config.py
+++ b/src/runtime/alpasim_runtime/config.py
@@ -315,6 +315,10 @@
 
     route_generator_type: RouteGeneratorType = RouteGeneratorType.MAP
     route_start_offset_m: float = 0.0
+    # Name of an "alpasim.route_generators" entry point to use instead of the
+    # built-in MAP/RECORDED generators. When set, route_generator_type is
+    # ignored. None (default) preserves existing behavior exactly.
+    route_generator_plugin: str | None = None
 
     # Whether to send optional messages to the driver
     send_recording_ground_truth: bool = False
diff --git a/src/runtime/alpasim_runtime/route_generator.py b/src/runtime/alpasim_runtime/route_generator.py
--- a/src/runtime/alpasim_runtime/route_generator.py
+++ b/src/runtime/alpasim_runtime/route_generator.py
@@ -7,6 +7,7 @@
 from typing import final
 
 import numpy as np
+from alpasim_plugins.plugins import route_generators as route_generator_registry
 from alpasim_runtime.config import RouteGeneratorType
 from alpasim_utils.geometry import Polyline, Pose
 from trajdata.maps import VectorMap
@@ -41,6 +42,7 @@
         vector_map: VectorMap,
         route_generator_type: RouteGeneratorType,
         route_start_offset_m: float = 0.0,
+        route_generator_plugin: str | None = None,
     ) -> "RouteGenerator | None":
         """
         Factory method to create a RouteGenerator
@@ -49,9 +51,18 @@
           vector_map: the map data
           route_generator_type: the type of route generator to create
           route_start_offset_m: approximate distance ahead of the ego projection where routes start
+          route_generator_plugin: name of an "alpasim.route_generators" entry point to use
+            instead of the built-in types below. When set, route_generator_type is ignored.
         Returns:
           A route generator of the specified type, or None if route generation is disabled
         """
+        if route_generator_plugin is not None:
+            plugin_cls = route_generator_registry.get(route_generator_plugin)
+            return plugin_cls.from_context(
+                recorded_waypoints_in_local,
+                vector_map,
+                route_start_offset_m=route_start_offset_m,
+            )
         if route_generator_type == RouteGeneratorType.NONE:
             return None
         elif route_generator_type == RouteGeneratorType.RECORDED:
diff --git a/src/runtime/alpasim_runtime/unbound_rollout.py b/src/runtime/alpasim_runtime/unbound_rollout.py
--- a/src/runtime/alpasim_runtime/unbound_rollout.py
+++ b/src/runtime/alpasim_runtime/unbound_rollout.py
@@ -186,6 +186,7 @@
     planner_delay_us: int
     route_generator_type: RouteGeneratorType
     route_start_offset_m: float
+    route_generator_plugin: str | None
     send_recording_ground_truth: bool
     nre_runid: str
     nre_version: str
@@ -323,6 +324,7 @@
             pose_reporting_interval_us=simulation_config.pose_reporting_interval_us,
             route_generator_type=simulation_config.route_generator_type,
             route_start_offset_m=simulation_config.route_start_offset_m,
+            route_generator_plugin=simulation_config.route_generator_plugin,
             send_recording_ground_truth=simulation_config.send_recording_ground_truth,
             vehicle_config=vehicle,
             vector_map=vector_map,
diff --git a/src/runtime/alpasim_runtime/event_loop.py b/src/runtime/alpasim_runtime/event_loop.py
--- a/src/runtime/alpasim_runtime/event_loop.py
+++ b/src/runtime/alpasim_runtime/event_loop.py
@@ -161,6 +161,7 @@
             vector_map=self.unbound.vector_map,
             route_generator_type=self.unbound.route_generator_type,
             route_start_offset_m=self.unbound.route_start_offset_m,
+            route_generator_plugin=self.unbound.route_generator_plugin,
         )
 
         self._runtime_evaluator = RuntimeEvaluator(
diff --git a/src/runtime/tests/test_event_loop.py b/src/runtime/tests/test_event_loop.py
--- a/src/runtime/tests/test_event_loop.py
+++ b/src/runtime/tests/test_event_loop.py
@@ -112,6 +112,7 @@
         planner_delay_us=0,
         vector_map=None,
         route_generator_type="RECORDED",
+        route_generator_plugin=None,
         route_start_offset_m=0.0,
         rollout_uuid="rollout",
         scene_id="scene",
```

A plugin author registers a `RouteGenerator` subclass under the `alpasim.route_generators` entry-point group (mirroring `alpasim.models`'s `[project.entry-points."alpasim.models"]` convention exactly) and implements a `from_context(cls, recorded_waypoints_in_local, vector_map, route_start_offset_m=0.0)` classmethod - documented as the expected contract, not `ABC`-enforced, for the reason above.

Worth calling out explicitly: `vector_map` (`UnboundRollout.vector_map: VectorMap | None`) can already be `None` today - the built-in `RouteGeneratorMap` would already fail if selected with no map data available, this isn't a new failure mode introduced here. A plugin that doesn't need map data (e.g. sourcing routes from an external service) can simply ignore the argument; one that does needs the same `None`-handling discipline the built-in map generator already implicitly requires.

## Verification performed

- `git apply --check` clean against a fresh clone of `main`.
- `py_compile` clean on all 5 touched source files.
- `black --check` / `isort --check --profile black` clean on all 6 touched files (including the test).
- Confirmed `UnboundRollout` (`unbound_rollout.py`) has exactly one construction site in the whole runtime package (itself), so adding a new non-default field is safe - no other caller needed updating.
- **Found and fixed a real regression before considering this final:** `test_event_loop.py`'s `test_initial_ego_context_uses_all_gt_samples_through_first_policy` mocks `unbound` as a `SimpleNamespace` without `route_generator_plugin`. `event_loop.py` now reads `self.unbound.route_generator_plugin` unconditionally, which would raise `AttributeError` on that mock even though `RouteGenerator.create` itself is separately mocked in the same test (the `AttributeError` happens evaluating the argument, before the mocked call is ever reached). Fixed by adding the field to that one mock (included in the diff above).
- Extracted the modified `RouteGenerator.create()` via `ast` and exercised it directly with a fake registered plugin class exposing `from_context`:
  - `route_generator_plugin` set → registry is used, `route_generator_type` is ignored entirely (verified by deliberately passing `RouteGeneratorType.NONE` alongside a plugin name and confirming the plugin path still wins).
  - `route_generator_plugin=None` → both `NONE` (returns `None`) and `RECORDED` (constructs `RouteGeneratorRecorded`) still behave exactly as before - the existing dispatch is provably untouched by this change.
- Searched for other tests calling `RouteGenerator.create` directly (`test_route_generator.py`) - all pass keyword args without `route_generator_plugin`, unaffected by the new defaulted parameter.

**Honest limitation:** this verifies the wiring and the fallback/opt-in behavior thoroughly, but not an actual third-party plugin package being discovered via real `importlib.metadata.entry_points()` at runtime (no such package exists to install and test against here). The registry mechanism itself (`PluginRegistry`) is untouched, pre-existing, and already relied on for four other extension points, so this is a lower-risk gap than it might sound.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b feat/route-generator-plugin
git am third_party/alpasim_overrides/upstream-proposals/route-generator-plugin.patch  # patch is git-am-ready, own Subject/body
git push fork feat/route-generator-plugin
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:feat/route-generator-plugin \
  --title "runtime: make RouteGenerator selectable via the alpasim.route_generators plugin registry" \
  --body-file <PR description derived from the "Why" section above>
```
