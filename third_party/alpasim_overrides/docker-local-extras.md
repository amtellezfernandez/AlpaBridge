# Proposed upstream PR: a `docker_local` extras group for headless runtime images

**Status:** re-cut 2026-08-12 against `1e801ca`, whose `all` extra gained `alpasim-trafficsim`. Applies cleanly to `main` @ `1e801ca`; not yet opened.

**Related:** the [ARM64 Docker build proposal](./arm64-docker-build.md) is the Docker-side half of this same fix - it installs exactly this package list (editable) instead of `uv sync --extra all` when building for ARM64. They're meant to be read together.

## Why

The existing `all` extras group in `pyproject.toml` installs every workspace package, including some that either can't resolve on ARM64 (`alpasim-tools` pulls PyQt5, no aarch64 wheel) or aren't needed at all inside a headless runtime container (`alpasim_driver`/`alpasim_plugins` run on the host in an external-driver setup, not in the runtime containers; `alpasim_wizard` is launched on the host too). There's currently no narrower extras group for "just what a headless local-external-driver runtime image needs."

## The change

Add a `docker_local` extras group listing exactly the packages a headless runtime image needs, with a comment explaining each deliberate exclusion.

```diff
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -37,6 +37,24 @@
   "alpasim-trafficsim",
 ]
 
+# Core packages needed inside headless local-external-driver Docker images.
+# This intentionally excludes:
+# - alpasim-tools: pulls PyQt5, which does not resolve on Linux aarch64
+# - alpasim_driver / alpasim_plugins: the external driver runs on the host, not in
+#   the runtime containers, and its dependency stack pulls x86-only packages such as
+#   tensordict through the upstream learned-driver models.
+# - alpasim_wizard: the wizard is launched on the host, not in the runtime image.
+# - alpasim-trafficsim: disabled by default (trafficsim=disabled); add it back if
+#   your deployment enables trafficsim=catk.
+docker_local = [
+  "alpasim_controller",
+  "alpasim_eval",
+  "alpasim_grpc",
+  "alpasim-runtime",
+  "alpasim_utils",
+  "alpasim-physics",
+]
+
 # -- Plugin extras --
 transfuser = ["alpasim_transfuser"]
```

**Note on `alpasim-trafficsim`:** current `main` has added a `trafficsim` package/extras group since this patch was first written (not present when we originally wrote it). It's excluded from `docker_local` here because trafficsim is disabled by default (`trafficsim=disabled`, per `CHANGELOG.md`) - not an oversight, but flagging it explicitly since it's the one judgment call in this list rather than a mechanical exclusion. If a deployment enables `trafficsim=catk`, it would need to be added back.

## Verification performed

- `git apply --check` clean against a fresh clone of `main`.
- Parsed the resulting file with Python's `tomllib` - valid TOML, `docker_local` resolves to exactly the intended 6 entries.
- Cross-checked each of the 6 package names against the real `name = "..."` field in each workspace member's own `pyproject.toml` (`src/controller`, `src/eval`, `src/grpc`, `src/runtime`, `src/utils`, `src/physics`) - all six match exactly, including the pre-existing underscore/hyphen naming inconsistency across packages (`alpasim_controller` vs. `alpasim-runtime`, etc.) - not something this patch introduces or needs to fix, just matched as-is.
- Confirmed `trafficsim=disabled` is the documented default before excluding `alpasim-trafficsim`, rather than assuming.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b feat/docker-local-extras
git am third_party/alpasim_overrides/docker-local-extras.patch  # patch is git-am-ready, own Subject/body
git push fork feat/docker-local-extras
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:feat/docker-local-extras \
  --title "packaging: add a docker_local extras group for headless runtime images" \
  --body-file <PR description derived from the "Why" section above>
```
