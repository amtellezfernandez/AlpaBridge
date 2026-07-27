# Proposed upstream PR: ARM64-safe package sync in the Docker build

**Status:** drafted and verified with a real `docker build` on real ARM64/Blackwell hardware (NVIDIA GB10) against `NVlabs/alpasim` `main` (commit `3032e0c`), not yet opened.

**Related:** the [`docker_local` extras proposal](./docker-local-extras.md) documents exactly which packages are safe to install on ARM64 and why - this PR is the Docker-side half of the same fix; they're meant to land together (or at least reference each other), though each applies independently.

## Why

The Dockerfile already detects architecture at the base-image level:

```dockerfile
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04 AS base-amd64
FROM nvcr.io/nvidia/pytorch:25.08-py3 AS base-arm64
ARG TARGETARCH
FROM base-${TARGETARCH}
```

But the later dependency-install step doesn't:

```dockerfile
RUN --mount=type=secret,id=netrc,target=/root/.netrc \
    --mount=type=cache,target=/root/.cache/uv \
    sh -c 'if [ -f /root/.netrc ]; then export NETRC=/root/.netrc; fi && uv sync --extra all'
```

`--extra all` pulls in every package group, including some with x86-only dependency chains (`alpasim-tools` pulls PyQt5, which has no aarch64 wheel; `alpasim_driver`/`alpasim_plugins`' dependency stack pulls x86-only packages such as `tensordict` via the built-in learned-driver models). None of those are needed for a headless local-external-driver image - the external driver runs on the host, and the runtime-side containers only need the core simulation packages.

## The change

Three independent fixes were needed to get a real ARM64 build passing - not just the one originally drafted here. Building against a naive first draft on real hardware surfaced two more blockers that static inspection had missed:

1. **The intended fix:** branch the dependency-install step on `$TARGETARCH`. On ARM64, install only the specific packages a headless runtime image actually needs (editable, matching how the rest of the Dockerfile works); everywhere else, unchanged (`uv sync --extra all`).
2. **A real, separate build blocker found on hardware:** the ARM64 base image (`nvcr.io/nvidia/pytorch:25.08-py3`) has no NVIDIA CUDA apt repository configured at all - only plain Ubuntu ports repos. The Dockerfile's `apt-get install ... datacenter-gpu-manager-4-cuda12` line only works today because the *x86* base image (`nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04`) ships that repo pre-configured. On ARM64 it fails immediately with `E: Unable to locate package datacenter-gpu-manager-4-cuda12`, before ever reaching fix #1. Fix: install NVIDIA's `cuda-keyring` package (from `developer.download.nvidia.com`'s `ubuntu2404/sbsa` repo, matching the base image's Ubuntu 24.04/aarch64) on the ARM64 path only, before the `apt-get install`.
3. **A latent bug in fix #1 itself, only caught by actually running the build:** `ARG TARGETARCH` is declared once, before `FROM base-${TARGETARCH}`, but never redeclared after that `FROM`. Empirically (verified with minimal repro Dockerfiles), BuildKit does not carry that ARG's value into `RUN` instructions in the final stage when there are three or more named stages before it (as this Dockerfile has: `base-amd64`, `base-arm64`, `dcgm-exporter`) - `${TARGETARCH}` silently evaluates to empty there, so any `if [ "${TARGETARCH}" = "arm64" ]` check in that stage always takes the non-ARM64 branch, on any architecture. Fix: add a bare `ARG TARGETARCH` immediately after `FROM base-${TARGETARCH}`, which correctly re-scopes it into the stage.
4. **A fourth, related gap fixed the same way:** the unconditional PyG-extension install step (`torch-cluster`/`torch-scatter`/`torch-sparse`) further down also needs `torch` already importable in an isolated build environment to compile from source, and is hardcoded to an x86 CUDA build (`PYTORCH_VERSION=2.8.0+cu128`). Checked which packages actually need these: only `alpasim-trafficsim`'s `pyproject.toml` references `torch_geometric`/`torch-cluster` - none of `runtime`/`controller`/`eval`/`utils`/`physics`/`plugins`/`grpc` do - and `trafficsim` is already excluded from the ARM64 package set in fix #1 (and from `docker_local`, see that proposal). So this step is skipped entirely on ARM64 rather than adapted.

```diff
diff --git a/Dockerfile b/Dockerfile
--- a/Dockerfile
+++ b/Dockerfile
@@ -13,6 +13,7 @@ FROM nvcr.io/nvidia/pytorch:25.08-py3 AS base-arm64
 FROM nvcr.io/nvidia/k8s/dcgm-exporter:4.4.1-4.6.0-ubuntu22.04@sha256:b7a4241c608253aa829041cc3575ea57082491251a4a626bcdddc68eaf9a3101 AS dcgm-exporter
 ARG TARGETARCH
 FROM base-${TARGETARCH}
+ARG TARGETARCH
 
 COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
 COPY --from=dcgm-exporter /usr/bin/dcgm-exporter /usr/bin/dcgm-exporter
@@ -22,6 +23,10 @@ RUN printf '%s\n' \
     >> /etc/dcgm-exporter/default-counters.csv
 
 ARG DEBIAN_FRONTEND=noninteractive
+RUN if [ "${TARGETARCH}" = "arm64" ]; then \
+      curl -fsSL -o /tmp/cuda-keyring.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/sbsa/cuda-keyring_1.1-1_all.deb && \
+      dpkg -i /tmp/cuda-keyring.deb && rm -f /tmp/cuda-keyring.deb; \
+    fi
 RUN apt-get update && apt-get install -y \
     git \
     ffmpeg \
@@ -57,7 +62,20 @@ WORKDIR /repo
 
 RUN --mount=type=secret,id=netrc,target=/root/.netrc \
     --mount=type=cache,target=/root/.cache/uv \
-    sh -c 'if [ -f /root/.netrc ]; then export NETRC=/root/.netrc; fi && uv sync --extra all'
+    sh -c '\
+      if [ -f /root/.netrc ]; then export NETRC=/root/.netrc; fi && \
+      if [ "${TARGETARCH}" = "arm64" ]; then \
+        uv pip install --python /repo/.venv/bin/python \
+          -e /repo/src/plugins \
+          -e /repo/src/grpc \
+          -e /repo/src/utils \
+          -e /repo/src/controller \
+          -e /repo/src/eval \
+          -e /repo/src/runtime \
+          -e /repo/src/physics; \
+      else \
+        uv sync --extra all; \
+      fi'
 
 ARG PYTORCH_VERSION=2.8.0+cu128
 ARG TORCH_CLUSTER_VERSION=1.6.3
@@ -66,12 +84,16 @@ ARG TORCH_SPARSE_VERSION=0.6.18
 
 # Install PyG compiled extensions (torch-cluster, torch-scatter, torch-sparse)
 # from pre-built wheels matching the installed torch + CUDA versions.
-RUN PYG_WHEEL_URL="https://data.pyg.org/whl/torch-${PYTORCH_VERSION}.html" && \
-    uv pip install \
-        "torch-cluster==${TORCH_CLUSTER_VERSION}" \
-        "torch-scatter==${TORCH_SCATTER_VERSION}" \
-        "torch-sparse==${TORCH_SPARSE_VERSION}" \
-        -f "$PYG_WHEEL_URL"
+# Only trafficsim depends on these, and trafficsim is excluded from the arm64
+# headless-runtime package set above, so skip this step on arm64.
+RUN if [ "${TARGETARCH}" != "arm64" ]; then \
+      PYG_WHEEL_URL="https://data.pyg.org/whl/torch-${PYTORCH_VERSION}.html" && \
+      uv pip install \
+          "torch-cluster==${TORCH_CLUSTER_VERSION}" \
+          "torch-scatter==${TORCH_SCATTER_VERSION}" \
+          "torch-sparse==${TORCH_SPARSE_VERSION}" \
+          -f "$PYG_WHEEL_URL"; \
+    fi
 
 ENV UV_CACHE_DIR=/tmp/uv-cache
 ENV UV_NO_SYNC=1
```

Deliberately excludes on the ARM64 path: `alpasim-tools` (PyQt5, no aarch64 wheel), `alpasim_driver`/`alpasim_plugins` (the external driver runs on the host, not in the runtime containers, and its dependency stack pulls x86-only packages), `alpasim_wizard` (also launched on the host), `alpasim-trafficsim` (disabled by default, needs the PyG extensions this patch skips on ARM64).

## Verification performed

This was verified with a real, complete `docker build` on real ARM64/Blackwell hardware (an NVIDIA GB10), not just static inspection - which is exactly what caught fixes #2-#4 above:

- `git apply --check` clean against a fresh clone of `main`.
- **`docker build -t alpasim-arm64-test .` completed successfully end to end** on the GB10 machine, producing a 33.3GB image. Iterated through the real failures: first attempt failed on the DCGM/apt-get step (fix #2); second attempt's ARM64 branch silently no-op'd due to the TARGETARCH scoping bug, confirmed by the step completing suspiciously fast (0.2s) and reproduced in isolation with minimal repro Dockerfiles matching this file's exact stage structure (fix #3); third attempt failed on the unconditional PyG step (fix #4); fourth attempt succeeded completely.
- The build log confirms `TARGETARCH` resolves correctly after fix #3 - BuildKit prints the literal resolved value in each step's command line, showing `if [ "arm64" = "arm64" ]` and `if [ "arm64" != "arm64" ]` rather than an empty string.
- **Ran the built image**: `docker run --rm alpasim-arm64-test` and imported `alpasim_runtime`, `alpasim_controller`, `eval` (the actual top-level module name for the `alpasim_eval` distribution - a pre-existing naming inconsistency in this repo, not something this patch needs to fix), `alpasim_utils`, `alpasim_physics`, and `torch` (resolved to `2.13.0+cu130`, a real aarch64-native CUDA build) - all succeeded.
- Confirmed the excluded packages are genuinely absent from the built image: `import PyQt5` and `import tensordict` both raise `ModuleNotFoundError` inside the container.
- Confirmed via `grep` across every `src/*/pyproject.toml` that only `alpasim-trafficsim` references `torch_geometric`/`torch-cluster` - the packages installed on the ARM64 path have no dependency on the PyG extensions being skipped.

## How to open this, once approved

```bash
cd <clone of amtellezfernandez/alpasim tracking upstream main>
git checkout -b feat/arm64-docker-sync
git am docs/upstream-proposals/arm64-docker-build.patch  # patch is git-am-ready, own Subject/body
git push fork feat/arm64-docker-sync
gh pr create --repo NVlabs/alpasim --base main \
  --head amtellezfernandez:feat/arm64-docker-sync \
  --title "docker: install only the packages a headless runtime image needs on arm64" \
  --body-file <PR description derived from the "Why" section above>
```
