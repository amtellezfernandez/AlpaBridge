# Route-generator plugin proposal: AlpaSim PR #179

**Status:** implemented as [PR #179](https://github.com/NVlabs/alpasim/pull/179)
for [issue #150](https://github.com/NVlabs/alpasim/issues/150). The accompanying
patch is a five-commit `git am` mailbox exported from PR head `be78f3a`,
based on upstream `affc2eab`; applied there it reproduces the PR head tree
exactly. It is proposal material, not an automatically applied AlpaBridge
setup override.

The first three commits are the original proposal. The last two follow the
maintainer's review: plugins are selected through the existing
`route_generator_type` field rather than a parallel override field, and the
plugin registry reports entry points that fail to import instead of calling
them "not found".

## Motivation and scope

AlpaBridge's existing driver models consume the route supplied by AlpaSim.
The historical need to forward route geometry into PredictionInput was resolved
upstream; see [the route-waypoint proposal](route-waypoints-in-prediction-input.md).
That is distinct from this proposal, which lets the runtime select another
route source.

The built-in RECORDED and MAP strategies use the recorded trajectory. The
proposed hook allows an installed package to supply different route geometry
without replacing the recording. AlpaBridge does not currently ship a production
route-generator plugin. The integration test described below supplies an authored
turn as a test-only plugin to demonstrate the complete driver boundary.

An external routing integration could benefit from this hook. A simple
file-based route could instead be a built-in strategy. Selecting between those
options still requires a concrete deployment requirement. The current factory
does not provide scene identity, a rollout seed, or plugin-specific configuration;
the test's fixed scenario does not prove those inputs are unnecessary.

## Interface

A package registers a class in the `alpasim.route_generators` entry-point group.
Its `from_context(recorded_waypoints_in_local, vector_map,
*, route_start_offset_m=0.0)` method returns a RouteGenerator. The map can be None.

`SimulationConfig.route_generator_type` is a string. `MAP`, `RECORDED` and
`NONE` keep their built-in meaning; any other value names a plugin. The
`RouteGeneratorType` enum is removed. Built-in names are reserved: a plugin
registered under one can never be selected, and startup logs a warning. Built-in
routing does not import the optional plugin package.

The name is resolved in `parse_simulator_config`, so an unknown name raises
PluginNotFoundError before services start, as the enum did, rather than once
per rollout. Without alpasim_plugins installed, a non-built-in name raises
ValueError. The registry is publicly exported from alpasim_plugins and included
in plugin information. The upstream documentation includes registration and
configuration examples.

## Executed integration test

[tests/test_runtime_route_plugin.py](../../tests/test_runtime_route_plugin.py)
checks the actual path:

1. Discover the test-only authored route via distribution entry-point metadata.
2. Convert structured SimulationConfig and construct a real UnboundRollout and
   EventBasedRollout from a synthetic scene.
3. Run PolicyEvent with the selected generator and the real runtime DriverService.
4. Send observations and routes over a localhost gRPC connection to the real
   AlpaBridgeDriverService running the route-following model.
5. Compare received geometry and the resulting prediction against a RECORDED
   control run with the same ground-truth trajectory.

The four cases cover headings of 0 and 90 degrees in a translated local frame,
with start offsets of 0 and 8 metres. The recorded control predicts straight
ahead; the authored route produces a predicted lateral displacement exceeding
5 metres. The test also verifies session teardown.

Only evaluation and unused backing services are mocked. No renderer, physics,
traffic simulation, dataset road-validity check, or complete closed-loop run is
performed. Short recorded routes can carry NaN padding; the driver intentionally
filters it. Float32 frame transforms are compared with a 0.1 mm tolerance.

## Validation on 2026-09-23 (PR head `be78f3a`)

- AlpaSim runtime suite: 522 passed, including the two MAP route tests on their
  Git LFS scene fixtures (one test deselected by the suite's own configuration).
- AlpaSim plugin tests: 9 passed; two driver-model registry tests fail only
  because the environment's installed driver package predates the branch, and
  fail identically without these changes.
- This repository's integration test: 4 passed. Against the original PR head
  `6b2e0b8` it skips with a message naming the required design.
- AlpaBridge complete suite against the PR branch: 477 passed, 34 subtests
  passed. `tests/test_alpasim_integration.py` runs without the AlpaSim source
  trees on `PYTHONPATH`, whose own `tests` packages otherwise shadow this
  repository's.
- black 24.10.0, isort 5.13.2 and flake8 7.1.1 at the upstream pre-commit
  settings pass on every changed Python file; Ruff passes for the AlpaBridge
  test.

## Validation on 2026-09-10 (original PR head `6b2e0b8`)

- AlpaBridge complete suite in the shared AlpaSim environment: 478 passed,
  34 subtests passed, including all four new gRPC integration cases.
- AlpaSim route-generator, event-loop, unbound-rollout, and policy-event tests:
  63 passed, one dataset-dependent map test deselected.
- The runtime CI invocation now includes `--with-editable ../plugins` so optional
  route-plugin discovery tests run; the equivalent focused local command passed
  all four plugin-related tests.
- Ruff passes for the new AlpaBridge test; applicable upstream pre-commit checks
  pass for the workflow change.

The excluded map test requires an 83 MB Git LFS fixture. Driver-model registry
tests requiring uninstalled VLA packages are not part of the focused runtime run.
Validation used protobuf bindings regenerated from the tested AlpaSim branch.

To reproduce the integration test, install the runtime and plugins packages from
the PR branch in an environment with matching generated protobuf bindings,
plus AlpaBridge's test dependencies. From the AlpaBridge checkout:

```bash
ALPASIM_ROOT=/path/to/alpasim
PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$ALPASIM_ROOT/.venv/bin/python" -m pytest tests/test_runtime_route_plugin.py -v
```

A dependency-light AlpaBridge environment skips this file if the runtime or
PR #179 registry is unavailable. Successful integration validation must report
four passing cases, not a skip.
