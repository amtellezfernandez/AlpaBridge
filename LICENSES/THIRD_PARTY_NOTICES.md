# Third-Party Notices

This repository is licensed under the BSD 3-Clause License (see [LICENSE](../LICENSE)),
with the exception of the third-party material listed below.

## NVIDIA AlpaSim override files

The AlpaSim override layers at
[`third_party/alpasim_overrides/`](../third_party/alpasim_overrides) and the packaged
copy at [`src/wod2sim/alpasim_overrides/`](../src/wod2sim/alpasim_overrides) contain
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

## NVIDIA AlpaSim protocol-replay media

[`docs/assets/readme/alpasim-protocol-replay.mp4`](../docs/assets/readme/alpasim-protocol-replay.mp4)
and its
[`animated README preview`](../docs/assets/readme/alpasim-protocol-replay.gif)
contain front-camera frames extracted from the official AlpaSim integration
fixture `src/runtime/tests/data/integration/rollout.asl` at upstream commit
`049f70fbfe8207e1efd4831a6c3e78a38703d473`. The exact source URL and SHA-256
are recorded in
[`artifacts/external/alpasim_protocol_replay/manifest.json`](../artifacts/external/alpasim_protocol_replay/manifest.json).

The upstream fixture is part of NVIDIA AlpaSim:

> SPDX-License-Identifier: Apache-2.0
> Copyright (c) 2025-2026 NVIDIA Corporation

WOD2Sim modified the rendered media by selecting the wide-camera stream,
pairing frames with executed `Drive` calls, and adding comparison plots,
measurements, labels, and contract-audit results. The upstream portion is
redistributed under the Apache License, Version 2.0; the full license text is
included at [`Apache-2.0.txt`](Apache-2.0.txt).

## NAVSIM EgoStatusMLP reference implementation and checkpoint

[`src/wod2sim/simulator/navsim_ego_status_mlp.py`](../src/wod2sim/simulator/navsim_ego_status_mlp.py)
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

## IEEE conference LaTeX class

[`paper/cvm/ieeeconf.cls`](../paper/cvm/ieeeconf.cls) is the unmodified
conference class distributed through the IEEE PaperPlaza support package linked
by the target conference's author instructions. It is copyright 1993-2002 by Gerry Murray,
Silvano Balemi, Jon Dixon, Peter Nuechter, Juergen von Hagen, and Michael Shell.

The class is distributed under the Perl Artistic License. A full copy of that
license is included at [`Artistic-1.0.txt`](Artistic-1.0.txt). The contribution,
copyright, warranty, and license notices are retained in the class file.
