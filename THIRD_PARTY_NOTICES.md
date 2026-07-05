# Third-Party Notices

This repository is licensed under the BSD 3-Clause License (see [LICENSE](LICENSE)),
with the exception of the third-party material listed below.

## NVIDIA AlpaSim override files

The AlpaSim override layers at
[`third_party/alpasim_overrides/`](third_party/alpasim_overrides) and the packaged
copy at [`src/wod2sim/alpasim_overrides/`](src/wod2sim/alpasim_overrides) contain
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
[`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt). Original copyright and
SPDX headers are retained in the files themselves; modifications made in this
repository are described in
[`third_party/alpasim_overrides/README.md`](third_party/alpasim_overrides/README.md).

AlpaSim itself is **not** bundled in this repository; the runtime expects a
separate AlpaSim checkout as described in the README.
