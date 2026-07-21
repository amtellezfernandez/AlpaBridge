# AlpaBridge Documentation

| Guide | Purpose |
| --- | --- |
| [Getting started](getting-started.md) | Install AlpaBridge, connect an AlpaSim checkout, and materialize a run. |
| [Design](design.md) | External-driver architecture, policy presets, trajectory conversion, and validation. |
| [WOMD targeting](womd-targeting.md) | WOMD/Waymax scope, real camera/LiDAR data formats, and compatible datasets. |
| [Reproduction](reproduction.md) | Plan or execute a run and retain its configuration and evidence. |
| [AlpaSim E2E compatibility](challenge-compatibility.md) | Package and run the evaluator-owned external-driver path. |
| [CLI](cli.md) | Public commands, development targets, and the conformance tier. |
| [Changelog](changelog.md) | Adapter release history. |

The repository does not install AlpaSim, redistribute gated scene assets, or
ship learned-policy checkpoints. Start with the dependency-light
`constant_velocity` or `route_following` preset, then connect a learned policy
only after matching its required observations, coordinates, timing, and route
inputs to the adapter.
