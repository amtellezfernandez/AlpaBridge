# Proposed upstream PR: a free-form pass-through field for third-party model config

**Status:** drafted and fully verified against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened.

## Why

`ModelConfig` (`schema.py`) is a fixed dataclass with a specific set of named fields (`model_type`, `checkpoint_path`, `device`, `tokenizer_path`, `use_classifier_free_guidance_nav`, `force_determinism`). `model_type` is resolved dynamically via the `alpasim.models` plugin registry - a third party can register a whole new model class without changing driver code - but that model has no way to receive its *own* configuration through the normal config path: any key not already declared on `ModelConfig` is rejected by OmegaConf's structured-config validation at merge time. We hit this directly - needed a handful of custom parameters for a side experiment and ended up routing them through environment variables instead, since there was no other way in.

Confirmed this is really what happens, not assumed:

```
ConfigKeyError: Key 'my_custom_param' not in 'ModelConfig'
    full_key: my_custom_param
    object_type=ModelConfig
```

## The change

Add a plain `dict[str, Any]` field. OmegaConf's structured-config strictness applies to the *declared* fields of a dataclass, not to the contents of a dict-typed field within it - so `extra` is open to arbitrary keys while every other field on `ModelConfig` stays exactly as strict as before.

```diff
diff --git a/src/driver/src/alpasim_driver/schema.py b/src/driver/src/alpasim_driver/schema.py
--- a/src/driver/src/alpasim_driver/schema.py
+++ b/src/driver/src/alpasim_driver/schema.py
@@ -4,6 +4,7 @@
 """Configuration schema for driver service supporting multiple model backends."""
 
 from dataclasses import dataclass, field
+from typing import Any
 
 from omegaconf import MISSING
 
@@ -27,6 +28,12 @@
     tokenizer_path: str | None = None  # Only required for VAM
     use_classifier_free_guidance_nav: bool = False  # A1.5 only
     force_determinism: bool = False  # Alpamayo 1 only
+    # Free-form pass-through for third-party model plugins. OmegaConf's
+    # structured-config validation rejects unknown top-level keys on this
+    # dataclass, but a plain dict field like this one accepts arbitrary
+    # nested keys, so a plugin can take e.g. model.extra.my_param without
+    # ModelConfig needing to know about it in advance.
+    extra: dict[str, Any] = field(default_factory=dict)
 
 
 @dataclass
```

A plugin model's `from_config` classmethod reads its own parameters from `cfg.extra` (e.g. `cfg.extra.get("temperature", 0.7)`), the same `cfg` object it already receives.

## Verification performed

All three cases run against the real, patched module (not a standalone reimplementation of the dataclass):

```
old-style config merges fine: {}
plugin config merges fine: {'temperature': 0.9, 'top_k': 40}
top-level schema strictness preserved: ConfigKeyError
```

- Existing-style config (no `extra` key at all) merges cleanly, `extra` defaults to `{}` - fully backward compatible.
- A config with `model.extra.temperature` / `model.extra.top_k` merges cleanly and both values are accessible.
- A config with a genuinely unrelated unknown top-level key (`totally_unknown_key`, not under `extra`) still raises `ConfigKeyError` exactly as before - this doesn't loosen validation everywhere, only inside the one deliberately-open field.
- `git apply --check` clean against a fresh clone of `main`.
- `py_compile` / `black --check` / `isort --check --profile black` clean.
- Searched the driver test suite for any test constructing `ModelConfig` directly or asserting its exact field set - no hits, so nothing needed updating.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b feat/model-config-extra
git am third_party/alpasim_overrides/upstream-proposals/plugin-config-passthrough.patch  # patch is git-am-ready, own Subject/body
git push fork feat/model-config-extra
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:feat/model-config-extra \
  --title "driver: add a free-form pass-through field for third-party model config" \
  --body-file <PR description derived from the "Why" section above>
```
