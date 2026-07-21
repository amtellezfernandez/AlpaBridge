# Third-Party Notices

This repository is licensed under the BSD 3-Clause License (see [LICENSE](../LICENSE)),
with the exception of the third-party material listed below.

## NVIDIA AlpaSim override files

The AlpaSim override layers at
[`third_party/alpasim_overrides/`](../third_party/alpasim_overrides) and the packaged
copy at [`src/alpabridge/alpasim_overrides/`](../src/alpabridge/alpasim_overrides) contain
files derived from NVIDIA AlpaSim:

- `src/driver/src/alpasim_driver/models/__init__.py`
- `src/wizard/alpasim_wizard/deployment/docker_compose.py`
- portions of `local_checkout.patch` and `route_waypoints.patch` that quote
  upstream AlpaSim source in patch context

These files are:

> SPDX-License-Identifier: Apache-2.0
> Copyright (c) 2025-2026 NVIDIA Corporation

and are redistributed, with project-authored modifications, under the terms of the
Apache License, Version 2.0. A full copy of that license is included at
[`Apache-2.0.txt`](Apache-2.0.txt). Original copyright and
SPDX headers are retained in the files themselves; modifications made in this
repository are described in
[`third_party/alpasim_overrides/README.md`](../third_party/alpasim_overrides/README.md).

AlpaSim itself is **not** bundled in this repository; the runtime expects a
separate AlpaSim checkout as described in the README.

## NVIDIA AlpaSim run media

[`artifacts/external/alpasim_navsim_reactive_rollout/camera-map.mp4`](../artifacts/external/alpasim_navsim_reactive_rollout/camera-map.mp4)
and its three derived previews
([full frame](../docs/assets/readme/alpasim-closed-loop.gif),
[map-only crop](../docs/assets/readme/alpasim-trajectory-map.gif),
[map-only divergence clip](../docs/assets/readme/alpasim-closed-loop-divergence.gif))
contain AlpaSim map output and a recorded camera frame from the official public
AlpaSim fixture
`src/runtime/tests/data/mock_video_model/clipgt-0b10bce8-61f1-4350-8577-cf3c9493ffc3.usdz`
at upstream commit `9177bd0bec547d7516cc77d1864e943780ef7e7a`.
The exact source URL and SHA-256 are recorded in the retained
[`manifest`](../artifacts/external/alpasim_navsim_reactive_rollout/manifest.json).

The upstream fixture is part of NVIDIA AlpaSim:

> SPDX-License-Identifier: Apache-2.0
> Copyright (c) 2025-2026 NVIDIA Corporation

AlpaBridge derived the preview directly from AlpaSim's retained run video. The
upstream portion is redistributed under the Apache License, Version 2.0; the
full license text is included at [`Apache-2.0.txt`](Apache-2.0.txt).

## AlpaSim dynamic-camera scene render

[`artifacts/external/alpasim_dynamic_camera_rollout/camera-map.mp4`](../artifacts/external/alpasim_dynamic_camera_rollout/camera-map.mp4),
its camera-only crop `camera.mp4` in the same directory, and their five
derived previews
([full frame](../docs/assets/readme/alpasim-dynamic-camera-full.gif),
[camera-only](../docs/assets/readme/alpasim-dynamic-camera.gif),
[single frame used in the README's before/after example](../docs/assets/readme/example-input.png),
[motion-shadow comparison](../docs/assets/readme/alpasim-motion-shadow.gif) —
a per-frame blend of the real camera-only crop with itself at a `0.6`s and
`1.2`s delay, no synthetic content added)
contain a live AlpaSim `sensorsim` render of gated scene
`clipgt-81b0e06d-96e6-4832-99c1-a4084b54ca97`, one of the scenes in this
repository's `front_camera_10scene_smoke` / `front_camera_30scene_merged`
scene presets. Unlike the NAVSIM reactive rollout below, this scene is not
part of AlpaSim's public test-fixture set; the maintainer has confirmed
they hold the rights needed to redistribute this rendered clip. The
retained run configuration and hashes are in the
[`manifest`](../artifacts/external/alpasim_dynamic_camera_rollout/manifest.json).
The behavior-cloned checkpoint used to drive this rollout is private and is
not included in this repository.

## README camera-comparison preview

[`docs/assets/readme/alpasim-camera-comparison.gif`](../docs/assets/readme/alpasim-camera-comparison.gif)
and its source
[`alpasim-camera-comparison.mp4`](../docs/assets/readme/alpasim-camera-comparison.mp4)
are a side-by-side composite of the two camera-only crops above (the
dynamic-camera and NAVSIM reactive rollouts) with AlpaBridge-authored text
labels overlaid. No new AlpaSim scene or checkpoint content is
introduced; both notices above apply to the pixels this composite reuses.
Superseded in the README by the two-rollout composite below, kept as a
cross-link in both evidence READMEs.

## README two-rollout demo composite

[`docs/assets/readme/alpasim-demo-two-rollouts.gif`](../docs/assets/readme/alpasim-demo-two-rollouts.gif),
shown at the top of the README, stacks a tighter crop of each rollout's
own map panel beside its own camera-only crop, both taken directly from
that rollout's `camera-map.mp4` (top: dynamic-camera rollout; bottom:
NAVSIM reactive rollout). AlpaBridge-authored text overlays are burned
into each panel: a scene/rollout/checkpoint provenance line on both map
panels, the retained `wrong_lane` / `dist_to_gt_location` metric values
on the NAVSIM map panel (from that run's `manifest.json`), and a LIVE /
STATIC label on each camera panel. No AlpaSim pixel content is otherwise
altered, and no new scene or checkpoint content is introduced beyond what
the two notices above already cover.

## Waymo Open Dataset logo

The README's "What Is WOMD?" section hot-links Waymo's own dataset logo
directly from `waymo.com` (`https://waymo.com/static/images/dataset/WaymoOpenDatasetLogo.svg`);
it is not copied into this repository. The logo and the Waymo Open Motion
Dataset it identifies are © Waymo LLC. See
[waymo.com/open](https://waymo.com/open/) for the dataset itself and its
license terms, and Ettinger et al., ["Large Scale Interactive Motion
Forecasting for Autonomous Driving: The Waymo Open Motion
Dataset"](https://arxiv.org/abs/2104.10133) (2021) for the cited figures.

## Waymo Open Dataset example images

[`docs/assets/readme/wod-camera-lidar-example.png`](../docs/assets/readme/wod-camera-lidar-example.png)
(`docs/images/vehicle-3D-labeling-example.png` upstream) and
[`docs/assets/readme/wod-lidar-point-cloud-example.png`](../docs/assets/readme/wod-lidar-point-cloud-example.png)
(`tutorial/3d_point_cloud.png` upstream) are copied unmodified from the
`waymo-research/waymo-open-dataset` GitHub repository at commit
`99a4cb3ff07e2fe06c2ce73da001f850f628e45a`. SHA-256:
`1a9815d02605db479e36a0b720870a70812d464e024f87f6ba5f92ae43f48f2a` and
`7ed948b7282497249c598e15f193ab83541b4026b7493b142ca1d7f5066797cc`
respectively.

These files are:

> SPDX-License-Identifier: Apache-2.0
> Copyright (c) Waymo LLC

and are redistributed unmodified under the Apache License, Version 2.0; the
full license text is included at [`Apache-2.0.txt`](Apache-2.0.txt). They
illustrate real camera and LiDAR output from the Waymo Open Dataset
(Perception); they are not this repository's own data and are not
generated by AlpaSim or AlpaBridge.

## NAVSIM EgoStatusMLP reference implementation and checkpoint

[`src/alpabridge/simulator/navsim_ego_status_mlp.py`](../src/alpabridge/simulator/navsim_ego_status_mlp.py)
reproduces the published EgoStatusMLP architecture and input/output contract
from NAVSIM v1.1 source commit
`0811876c274e8b058ab2be9b3dcd4d37bd23f177`. The replay runner downloads the
official `ego_status_mlp_seed_0` checkpoint from
`autonomousvision/navsim_baselines` at revision
`32d89c0ae6e7c13c311f4a034002006c250afab0` and verifies SHA-256
`87d75b0f43d077ac3531370d7cccac98656d4e9b5ce5fa6618e28b7358b3a86b`.
The checkpoint is not redistributed in this repository.

NAVSIM and its baseline checkpoint repository are published under the Apache
License, Version 2.0. The full license text is included at
[`Apache-2.0.txt`](Apache-2.0.txt).
