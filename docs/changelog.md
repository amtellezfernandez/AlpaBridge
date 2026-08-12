# Changelog

All notable adapter-release changes are tracked here.

## Unreleased - 2026-08-12

- Re-baselined the AlpaSim overrides onto `NVlabs/alpasim` `main` @ `1e801ca`
  (the August 2026 public sync). Before this, AlpaBridge did not work against
  current AlpaSim at all: both applied patches failed to apply, and the driver
  model-registry override silently removed a driver upstream had just added.
  - `local_checkout.patch` re-authored. `EgoDriverService` moved from async
    `grpc.aio.ServicerContext` to sync `grpc.ServicerContext`, gained
    `@log_call` and a `_sessions_lock`, and renamed
    `session.desired_cameras_logical_ids` to `session.frame_caches`; upstream
    also dropped `close_session`'s own existence check, so its bare `del` now
    raises `KeyError` where it used to raise a descriptive one. The same five
    session RPCs are guarded as before, now inside `_sessions_lock` where
    upstream locks that dict, with `drive` returning upstream's own established
    no-op value (an empty `Trajectory`). The Dockerfile/pyproject hunks follow
    `--extra all` becoming `--extra all --extra recipes` and `all` gaining
    `alpasim-trafficsim`.
  - `route_waypoints.patch` retired and replaced by `session_metadata.patch`.
    Upstream implemented the route half itself: `PredictionInput` now carries
    `route` and `inference_seed`, backed by a new `Session.route`. No AlpaBridge
    consumer changed — `route_waypoints_from_input` already probed `route` and
    unwrapped `.waypoints`. The remaining patch adds only `session_uuid` and
    `debug_scene_id`, which upstream still does not forward and which
    `AlpaSimContractValidator` needs to reset per-session state at a session
    boundary (without it the frozen-camera check carries state across one).
  - Added `Alpamayo2Model` to the driver model-registry override. Upstream's
    August sync added the Alpamayo 2 driver to `models/__init__.py`, but that
    file is one AlpaBridge ships a full copy of, and the copy step always runs
    last and wins — so `alpabridge-setup` was un-registering a driver that
    upstream had just shipped.
  - `prediction_runtime_metadata` now reads upstream's `inference_seed` for
    seed telemetry, ahead of the older `runtime_random_seed` name it used to
    inject itself.
- Closed the drift gap that hid the registry breakage:
  `test_packaged_and_tracked_alpasim_overrides_stay_in_sync` derives its file
  list from the two override roots instead of a hand-maintained tuple that had
  omitted `models/__init__.py` — the one file that then drifted.
- Added `deploy=local_external_driver_video_model`: the first deployment shape that can run
  on ARM64. Both the policy *and* the renderer are external services, so the wizard manages
  only `[physics, trafficsim, controller, runtime]` -- all of which build and run natively on
  aarch64 (verified on GB10). It selects AlpaSim's `runtime.renderer.kind=video_model`
  (OmniDreams/FlashDreams), which is built from source rather than pulled as the amd64-only
  NuRec image, and that is the whole reason an ARM target is possible.
  Two launcher changes fall out of the config, and both are the kind of thing that would
  only have surfaced *after* an ARM64 image build:
  - `+cameras=<n>cam` is no longer injected on this deploy. AlpaSim's video-model renderer
    derives the camera rig and calibration from the recorded USDZ seed frames, and its docs
    state plainly that a separate override must not be added -- it desynchronises the HD-map
    conditioning render from the visual seed frame and the generated video drifts. Enforced
    inside `_wizard_command` rather than at the call site, so no future caller has to
    remember it. Every other deploy still pins the rig.
  - The ARM64 preflight no longer blocks this target. That block exists because the
    NuRec/sensorsim image is amd64-only; this deploy has no sensorsim container at all.
- **Fixed the actual interface break with AlpaSim `1e801ca`: every policy returned a
  removed API.** Upstream replaced `ModelPrediction`'s `trajectory_xy`/`headings` with
  6-DoF candidates -- `candidate_positions` (K, T, 3) and `candidate_rotations`
  (K, T, 3, 3) -- so all six AlpaBridge policies died at the first `drive` call with
  `ModelPrediction.__init__() got an unexpected keyword argument 'trajectory_xy'`, after
  the renderer, physics and controller had already come up.
  The whole suite passed anyway, and that is the important part: `alpasim_contract` falls
  back to a local `ModelPrediction` stub when AlpaSim is not importable, and the stub still
  had the old signature. Tests exercised the stub; only a live rollout touched the real
  class. The stub now mirrors upstream's current signature exactly, so the suite tests the
  contract that actually ships.
  Policies keep returning the flat 2D plan they naturally produce. `make_model_prediction`
  is now the single place that knows AlpaSim's prediction shape, with
  `prediction_trajectory_xy` / `prediction_headings` for reading one back. An upstream
  change to that contract is now one edit, not six.
- Replaced stale `alpabridge-audit-run` advice that told you to "apply the route-waypoints
  AlpaSim override" on a command-proxy frame. That override was retired -- AlpaSim provides
  `PredictionInput.route` natively now -- so the advice pointed at a file that no longer
  exists. It now explains what a command-proxy frame actually means.
- Audited every remaining override against AlpaSim `1e801ca` rather than only the ones
  that failed loudly. Verified coherent: both patches apply; the `models/__init__.py` copy;
  all five driver configs under `simulator/alpasim_configs/driver/` validate against
  upstream's current `DriverConfig` structured schema; `run_sim_services` is upstream's list
  minus `"driver"` (the documented external-driver intent); and `use_localhost`,
  `external_services`, `runtime.endpoints.trafficsim.skip`, `startup_timeout_s`,
  `defines.renderer_entrypoint` and `defines.nre_cache_size` all still exist upstream. Two
  did not hold up:
  - **Removed `Dockerfile.amd64`.** A stale single-stage fork of a pre-multi-arch upstream
    `Dockerfile`, referenced by no code path, whose own header said to build it as
    `alpasim-base:0.66.0` -- the tag AlpaBridge pins. It contains none of `dcgm-exporter`,
    `datacenter-gpu-manager`, `prometheus`, `TARGETARCH` or the `recipes` extra, and
    upstream's compose now *always* adds a prometheus service from that image, so an image
    built from it could not run a rollout. Upstream's `Dockerfile` selects its base by
    `TARGETARCH`, making a per-arch fork obsolete.
  - **`local_arm_external_driver.yaml` pinned `--max-workers=4`** where upstream's
    `base_config.yaml` uses `${defines.nre_max_workers}`. Same value today, but the override
    re-lists upstream's entire renderer command, so any literal it pins silently stops
    following upstream. It now references the define.
- Retiring an override now actually takes effect. `alpabridge-setup` only ever *copied*
  files, so a retired override survived forever in every checkout that had been set up --
  the checkout kept obeying a file AlpaBridge had disowned. Setup now also removes retired
  copies, gated on the file still being byte-identical to the version AlpaBridge shipped, so
  it can never delete something the user wrote.
- Rebased the `docker_compose.py` override onto upstream's current file. The shipped
  override was a fork of a much older upstream version and **hard-failed against AlpaSim
  `1e801ca`**: it iterated `container_set.runtime`, which upstream made a single
  `ContainerDefinition`, so a real rollout died with
  `TypeError: 'ContainerDefinition' object is not iterable` before any container started.
  Found by attempting an actual closed-loop rollout, not by reading the file -- the drift
  had been sitting there since at least 2026-07-01 (upstream has not touched that file
  since) and no test covered it.
  Rebasing takes upstream's current file as the base and re-applies only AlpaBridge's four
  intentional deltas (the `--array-job-dir` single-run normalisation, `pull_policy:
  missing`, and `pid: host` plus all-GPU reservations on the runtime service). Everything
  else the fork had silently reverted is now inherited: prometheus service handling,
  `RunMode.SERVER` port publishing, the `_netrc_secret_file` helper, the `umask 0000`
  command prefix, and escaping every `$` rather than only `\$`.
- Fixed two tests that only passed because of what happened to be absent from the
  environment:
  - The `docker_compose.py` override loader now stubs `fakepkg.schema`, needed since the
    rebased override inherits upstream's `from ..schema import RunMode`.
  - `test_vavam_driver_service_dispatches_to_vavam_model` asserted
    `pytest.raises(ImportError, match="requires torch")`, using the model's own
    optional-dependency guard as a proxy for "dispatch reached the model". That proxy only
    holds when torch is absent -- true in CI, false for anyone who has run
    `./scripts/bootstrap_alpasim_env.sh`, which installs torch into this repo's venv. With
    torch present the dispatch still worked and the test failed anyway, on a later
    `No module named 'vam'`. It now substitutes `VAVAMAlpaSimModel` and asserts what it was
    constructed with, which is the thing the test is named for.
- Fixed the ARM64 build path, which could not have worked as shipped. The re-authored
  `local_checkout.patch` gates its arm64 install subset on `${TARGETARCH}`, but
  upstream's `ARG TARGETARCH` is declared *before* `FROM base-${TARGETARCH}` and is
  therefore not in scope for `RUN` steps in the stage that `FROM` opens. Every arm64
  conditional expanded to `if [ "" = "arm64" ]` -- silently false -- so an aarch64 build
  quietly took the x86 path. This presents as a step completing suspiciously fast rather
  than as an error, which is how it survived review. `ARG TARGETARCH` is now re-declared
  inside the stage.
  Two further arm64 fixes moved into the applied patch for the same reason -- they only
  ever lived in `third_party/alpasim_overrides/arm64-docker-build.patch`, which is an
  upstream *proposal* that `alpabridge-setup` never applies, so an arm64 setup was
  missing them entirely:
  - The CUDA apt repo is configured on arm64, since `datacenter-gpu-manager-4-cuda12`
    comes from it and the arm64 base image does not have it. The repo path derives from
    the base image's own `/etc/os-release` instead of hardcoding `ubuntu2404`.
  - The PyG compiled extensions step is skipped on arm64: its wheel index is pinned to
    an x86 CUDA build (`2.8.0+cu128`) and publishes nothing for aarch64. Only
    `alpasim-trafficsim` needs them and it is already excluded from the arm64 subset.
- Fixed `alpabridge-setup` writing a stray `__init__.py` into the root of the user's
  AlpaSim checkout. `alpasim_overrides/__init__.py` is what makes the override payload an
  importable package inside AlpaBridge, but the copy step treated it as payload, so every
  setup dropped a file at the AlpaSim repo root -- untracked noise in that checkout, and
  enough to make Python treat the repo root as a package. Only the root-level marker is
  excluded; `src/driver/**/models/__init__.py` is a genuine override and still copies.
  Found by installing the built wheel into a clean venv and running
  `_apply_local_alpasim_overrides` against a pristine AlpaSim checkout, which is now the
  standing way to check this path: after the fix that checkout shows only the intended
  six modified files and three added ones.
- Assessed the two migrations the AlpaSim release calls for and confirmed both are
  no-ops for AlpaBridge, rather than assuming either way:
  - *"Alpamayo runs now reject camera images smaller than 320x576"* applies to the
    built-in `driver=alpamayo*` models. AlpaBridge ships its own driver configs
    (`simulator/alpasim_configs/driver/*.yaml`, `defaults: [_self_]`, own
    `model_type`), so it never selects those; and its policies resize whatever the
    renderer sends via `image_ops.resize_and_center_crop`, which cover-scales rather
    than assuming a minimum source size. The `cameras=1cam` group AlpaBridge pins
    from each preset's `inference.use_cameras` still exists alongside the new
    `1cam_1080`, so `+cameras=1cam` still resolves.
  - *"move custom `driver.rectification` intrinsics to matching
    `runtime.extra_cameras`"* applies to Sensorsim/NuRec deployments that set
    `driver.rectification`. AlpaBridge sets it nowhere, and its VaVAM support is its
    own external-driver adapter (`simulator/vavam_model.py`), not upstream's
    `driver=vavam_video_model` path, so there are no intrinsics to move.
- Flagged in `third_party/alpasim_overrides/README.md` that the seven upstream
  proposals are still verified only against `3032e0c`, which predates this
  release, and must be re-verified before any is opened.

## Unreleased - 2026-07-28

- Fixed `constant_velocity`/`route_following` forward-simulating standing
  still for the first ~1s of every real rollout: `baseline_drivers.py` read
  `prediction_input.speed` raw instead of going through the existing
  `corrected_speed_mps()` pose-derived fallback that `direct_actor_planner`/
  `token_dagger_bc`/`mpc_planner` already use. Confirmed this is a real,
  currently-occurring gap (not just a theoretical one) directly against live
  telemetry from this session's own rollouts: AlpaSim's `DynamicState`
  reported `speed_mps=0.0` for the first several frames of a session while
  `ego_pose_history` showed ~10.84 m/s of genuine motion (~8-10% of all
  frames in each run, concentrated at rollout start, matching the
  lagging/stale-`DynamicState` mechanism `corrected_speed_mps()`'s docstring
  already describes).

- Fixed a real rollout never terminating on its own: our tracked
  `docker_compose.py` override had fallen out of sync with AlpaSim's own
  current `deploy_all_services` (confirmed by diffing against the real
  upstream file at the pinned tag) and was missing
  `--exit-code-from runtime-0`/`--remove-orphans` and the `wizard.dry_run`
  early-return. Without `--exit-code-from`, `docker compose up` only
  returns once every service exits on its own - but physics/renderer/
  controller are long-running servers, not one-shot jobs, so a completed
  rollout's containers (and the wizard process waiting on them) just sat
  there indefinitely after the `runtime` container that actually drives
  the rollout finished. Verified by rerunning the same `constant_velocity`
  rollout end to end: it now completes, tears down its containers, and
  the audit/support-bundle steps run automatically, with no manual
  intervention needed.
- Fixed real closed-loop rollouts being completely broken on x86_64 (the
  primary supported platform) against the currently-pinned AlpaSim release:
  `alpabridge-launch`/`alpabridge-reproduce --execute` hardcode
  `deploy=local_external_driver` for the wizard invocation, but that Hydra
  config doesn't exist anywhere - not in AlpaBridge's own tracked
  overrides, and not in AlpaSim's current pinned release, which removed it
  in a May 2026 restructuring sync (confirmed by fetching its last real
  content from AlpaSim's own git history, from before that removal).
  AlpaBridge's ARM-specific override (`local_arm_external_driver.yaml`,
  the one deploy file that did exist) also referenced a
  `${defines.sensorsim_entrypoint}` variable and a `services.sensorsim` key
  that don't exist in the current schema (real names are
  `defines.renderer_entrypoint` and `services.renderer`), so its Blackwell
  renderer tuning was silently never applied. Restored a proper
  `local_external_driver.yaml` against the current wizard schema (dropping
  `driver` from `wizard.run_sim_services`, seeding
  `wizard.external_services` as a populated dict since Hydra's CLI-override
  merge can't target a dotted sub-key under a `None` container) and
  repaired the ARM file's variable/key names. This is exactly the class of
  bug the test suite structurally cannot catch on its own: CI and all
  existing tests only ever exercise `--mode print` (command-string
  construction), never actual Hydra config resolution - caught only by
  running a real `--execute` rollout end to end against a fresh AlpaSim
  clone at the exact pinned tag, through to a completed rollout with real
  aggregate metrics.
- Fixed a second, unrelated bug hit immediately after the first: AlpaSim's
  own current default scene camera config (`runtime.simulation_config.cameras`
  in `base_config.yaml`) now ships 2 cameras, but every public AlpaBridge
  preset declares only 1 (`camera_front_wide_120fov`) in its
  `inference.use_cameras`, and AlpaSim's driver framework hard-rejects any
  camera frame arriving outside a model's declared list
  (`Camera camera_front_tele_30fov not in desired cameras`). Added
  `_camera_group_for_preset()`, which derives a `+cameras=<n>cam` wizard
  override from each preset's own declared camera count, so scene camera
  config is always pinned to match the policy rather than left to
  whatever AlpaSim currently defaults to.
- Added `mpc_planner`, a fourth built-in policy backend and the first
  built-in that plans rather than uses closed-form kinematics: it
  forward-simulates a handful of candidate `(yaw_rate, acceleration)`
  control sequences through a simple unicycle model, scores each on
  route-tracking, hazard clearance, speed, and smoothness, and picks the
  cheapest — using only real-time, non-privileged signal, no learned
  model. Registered through both the `alpasim.models` entry point and
  `policy_registry.py`, with its own Hydra config, CLI preset, audit-log
  reader, and doctor/readiness surface entries, matching every other
  dependency-light baseline. Building it surfaced several real bugs (see
  below), since it was the first built-in to actually exercise some of
  this code's edge cases.

- Fixed `_yaw_from_quat_like` (the adapter's quaternion-to-yaw
  extraction, used by `SensorFreshnessGuard`'s pose-changed check): it
  hardcoded the pure-yaw shortcut `atan2(2wz, 1-2z²)`, which silently
  assumes no roll/pitch. AlpaSim's own real implementation
  (`utils_rs`'s `Pose.yaw()`) uses the full formula
  `atan2(2*(wz+xy), 1-2*(y²+z²))`. A combined ~10° roll+pitch (a
  plausible hard-brake-while-cornering moment) pushed the old formula's
  error past `SensorFreshnessGuard`'s own `0.01` rad pose-changed
  threshold — quantified with a direct numeric repro before and after.
  Also found and consolidated a second, independent copy of the same
  function in `alpasim_token_bc.py` (already correct, but silently able
  to re-diverge), and fixed a related crash: a quat object present but
  missing every field used to return `None` and crash
  `_pose_like_to_signature`'s final `round()` call.

- Fixed several places where a non-finite value (`NaN`/`inf`) silently
  passed as if benign instead of being rejected: hazards and oracle-actor
  proxy entries with `NaN` position/radius/velocity fields used to reach
  collision-cost math and, in one traced case, make Python's
  `min(inf, nan) == inf` read as *maximum* safety clearance for an
  actor at an unknown position — the worst possible wrong answer for a
  collision-avoidance planner. Added `math.isfinite` validation at the
  JSON-parsing choke points instead. Separately, consolidated four
  near-duplicate int-coercion helpers (across `promote_batch_summary.py`,
  `benchmark_readiness.py`, `benchmark_summary.py`, `batch_summary.py`),
  all missing `OverflowError` handling on `int(float('inf'))`, into one
  shared `alpabridge/cli/numeric.py`.

- Fixed `has_intervention()` flagging every single frame of every
  `constant_velocity`/`route_following` run as a driver intervention:
  its non-intervention whitelist only ever listed `maintain` and
  `direct_actor_planner`, not each baseline's own `action_mode` name.
  Also added the missing `mpc_planner` audit-export reader, which would
  have hit the same whitelist bug immediately.

- Fixed `SensorFreshnessGuard` losing track of a known session identity
  when a later `validate()` call came in unlabeled (`session_uuid=None`),
  and fixed `route_source` telemetry being able to disagree with the
  geometry actually driven, by giving both the telemetry and the driven
  path a single shared source of route-waypoint filtering.

- Fixed the CI wheel-smoke test's drift from the readiness CLI's actual
  image-tag check (`check_alpasim_readiness.py` printed a hardcoded
  `alpasim-base:0.66.0` regardless of `ALPASIM_BASE_IMAGE_TAG`
  overrides), and, separately, the wheel-smoke test's own hardcoded
  `MODEL_PRESETS` tuple assertion, which wasn't updated when
  `mpc_planner` was added — CI was red on every push for a few commits
  until this was caught and fixed.

- Restructured the tests for the two pieces of adapter logic confirmed,
  by direct comparison against AlpaSim's real source, to independently
  duplicate math AlpaSim itself implements (`_yaw_from_quat_like` vs.
  `utils_rs`'s `Pose.yaw()`; `segment_point_distance` vs.
  `Polyline.project_point`) to mirror AlpaSim's own test style in
  `src/utils/tests/test_utils_rs.py` / `test_polyline.py` — plain
  classes/functions, bare asserts, the same geometric test cases — so a
  maintainer of both projects has a familiar layout to compare against.
  Deliberately did not add `scipy` as a dependency just to match
  AlpaSim's own validation-library choice for one test.

- Added `VAVAM`, a public 318M-parameter video-action model policy
  backend ([Valeo VideoActionModel](https://github.com/valeoai/VideoActionModel)),
  with pose-reanchored inference caching for its slower-than-realtime
  inference rate, and generalized the AlpaSim E2E challenge driver into
  a reusable policy-serving framework rather than a single-purpose
  script. Retained real, hash-validated rollout evidence.

- Adopted the standard NVIDIA-org convention for AlpaSim override
  patches (`git format-patch`-generated, `git am`-applyable, self-
  labeling `Subject:`/body instead of a separate hand-maintained prose
  summary), after researching how other NVIDIA-org projects patch
  vendored dependencies. Drafted nine upstream proposals for
  `NVlabs/alpasim` itself in the same rigorous format (one `.md` covering
  why/what/verification/how-to-open plus a matching `.patch` per
  proposal) — prepared for a future PR, not submitted — and re-verified
  every one applies cleanly against AlpaSim's actual current upstream
  `main`. Consolidated the proposals directly into
  `third_party/alpasim_overrides/`, since every tracked override is, in
  that sense, already an implicit upstream proposal.

- Bumped the pinned AlpaSim release to `v2026.5`, fixed the override
  patches that broke against it, rebased `route_waypoints.patch` against
  AlpaSim's actual current `main`, and added automatic torch/torchvision
  compatibility verification during `alpabridge-setup`.

- Fixed AlpaBridge smuggling extra fields through `PredictionInput` and
  added a workaround for an AlpaSim zero-speed bug.

- Added `alpabridge-register-custom-scene` to close the gap for
  registering your own complete USDZ scene into AlpaSim's catalog, and
  collapsed real duplication in `policy_registry.py` (documenting, in
  the same pass, why the rest of its apparent repetition isn't actually
  duplication).

- Repositioned the README around capability rather than gaps: reframed
  Policy Backends by what each policy can do instead of what it lacks,
  added an Evaluation Paths section (evaluators are as pluggable as
  policies), a concrete Bring-Your-Own-Policy walkthrough, and split
  audience-specific content (how to run vs. advanced/developer material)
  out of the main README into dedicated docs. Fixed several accuracy
  regressions caught along the way (a stale GPU-requirement claim,
  "in-process"/"dependency-light" terminology drift, inconsistent
  command-invocation style across docs).

- Routine dependency bumps: `actions/checkout`, `actions/setup-python`,
  and `astral-sh/setup-uv` to their latest pinned versions (Dependabot).

## Unreleased - 2026-07-21

- Fixed the Mermaid diagram's text legibility: node styles had no
  explicit `color`, so GitHub's dark-theme Mermaid rendering fell back to
  a washed-out light text color on the light node fills. Added explicit
  `color:#0f172a` to every node style; verified in both light and dark
  rendering via `mermaid-cli`.
- Merged the "before" and "after" example images into one combined
  figure (`scripts/render_readme_example.py` now renders a single
  three-column `example-before-after.png` — camera frame, input fields,
  output trajectory — instead of two independently-sized matplotlib
  figures placed side by side, which never shared a height or baseline
  and read as mismatched).
- Restructured the Demo section's two rollout paragraphs into Map/Camera
  bullet points mirroring the image's actual left/right layout, instead
  of one dense paragraph covering both per rollout.

- Pre-public-release security pass: pinned the remaining unpinned GitHub
  Actions (`checkout`, `setup-python`, `upload-artifact`) to full commit
  SHAs, matching the existing `setup-uv` convention. Enabled GitHub's
  private vulnerability reporting for this repo and pointed
  `SECURITY.md` at it instead of an unlisted email address. Added
  defensive `.gitignore`/`.dockerignore` entries for common secret file
  patterns (`.env`, `*.pem`, `*.key`, `*credentials*`, `.netrc`) as
  belt-and-suspenders, since none were currently tracked. A parallel
  four-way review (secrets/PII, CI/workflow, source code, retained
  evidence artifacts + packaging) found no must-fix issues in any of
  those areas — redaction claims on the private-checkpoint rollout
  evidence were independently re-verified against the actual file
  contents, not just the docs' claims.

- Tightened README prose throughout, mainly the Demo and Scope sections:
  cut repeated hedging phrases ("not a mockup," "genuinely," "honestly,"
  restating the same reassurance in three different forms) down to one
  plain statement of each fact. No factual content removed — same
  claims, same numbers, roughly a third fewer words in the Demo section.

- Merged both rollout composites into a single stacked image
  (`alpasim-demo-two-rollouts.gif`, dynamic-camera on top, NAVSIM below)
  and burned real provenance directly into each map panel — scene ID,
  rollout ID, and checkpoint name/visibility, pulled straight from each
  run's `manifest.json` — instead of relying only on prose below the
  image. Also surfaced the NAVSIM rollout's retained `wrong_lane` flag
  and `16.29`m `dist_to_gt_location` divergence as a label directly on
  its map panel, where the maneuver is visible, since the retained
  metrics already document it and it was previously only mentioned in
  the caption text below the image. Explicitly noted in the same caption
  that `collision_any` and `offroad` are both `0` for this rollout, so
  the label doesn't read as a stronger claim than the data supports.

- Burned a small text label into each rollout's camera panel ("LIVE —
  motion-shadow trail from real frames" / "STATIC — camera-blind
  checkpoint (fixture frame, never changes)") so the contrast is
  unmistakable even without reading the surrounding prose — a static
  half of an otherwise-live GIF reads as broken at a glance otherwise,
  which is exactly the perception the dynamic-camera rollout was created
  to counter in the first place. Documented as an AlpaBridge-authored
  text overlay in the third-party notices, no AlpaSim pixel content
  otherwise altered.

- Brought the NAVSIM rollout into the same Demo section as the
  dynamic-camera rollout, as its own map+camera composite
  (`alpasim-navsim-map-camera.gif`), instead of a separate map-only
  section further down. Checked whether it could also get a real
  motion-shadow trail like the dynamic-camera rollout: frame-diffed its
  camera feed and confirmed it's genuinely frozen (`~0.008` mean pixel
  difference between frames 7 seconds apart, pure compression noise), so
  blending it with itself would show nothing real — shown here plainly
  instead, captioned as intentionally frozen, which now doubles as a
  direct visual contrast against the reactive rollout's ghost trail and
  ties into the existing frozen-camera negative control. Retimed its
  window to the run's actual divergence (the last ~8s, where the orange
  path visibly peels from the logged path into the intersection) and
  applied the same tight, no-border map crop used for the dynamic-camera
  rollout. Removed the now-redundant `alpasim-camera-comparison.gif`
  side-by-side from the main Demo flow (both camera feeds are already
  visible in the two rollout composites above it); the file itself is
  kept as a superseded cross-link in both evidence READMEs.

- Retimed and retightened `alpasim-map-camera-ghost.gif`: the previous
  5s-in/12s-long window spent most of its loop on a long straight stretch
  with no visible change. Rescanned the source and moved the highlight to
  the run's most dynamic 5 seconds (a car crossing ahead and the ego's
  turn, both visible as a curving trajectory line on the map panel and a
  curving route line in the camera panel), still starting far enough in
  for the motion-shadow blend to have full real history from frame 0.
  Also tightened the map panel's crop to the plotted square itself
  (`474x474` from precise border-pixel detection) instead of including
  ~60px of dead white margin around it.

- Sharpened the Scope section: led with what AlpaBridge is actually for
  (testing whether a policy drives in a live, closed-loop, photorealistic
  simulator) and bolded the boundary it doesn't cross ("put Waymo's
  streets inside AlpaSim") instead of a single flat sentence about not
  converting WOMD scenarios. Also fixed a stale test count (`237` to
  `243`) left over from tests added earlier this session.

- Replaced the diagram+footage composite hero with `alpasim-map-camera-ghost.gif`
  (renamed from `alpasim-demo-schema.gif`): AlpaSim's own 2D map view for the
  dynamic-camera rollout (cropped directly from that run's `camera-map.mp4`,
  same ego/agent boxes and planned path as the camera panel) placed beside its
  motion-shadow camera blend, both from the same real run — not a second
  simulator, not a mockup. The architecture diagram moved out of the
  composited image entirely and is now a separate, compact `flowchart LR`
  Mermaid diagram directly under the demo image, so it renders natively on
  GitHub (no rasterization, no blur) instead of being baked into GIF pixels.
  Deleted the now-unused `architecture-horizontal.svg`.

- Fixed `alpasim-demo-schema.gif`'s first frame showing no motion-shadow
  trail at all: the blend needs `1.2`s of prior frames, and the clip
  previously started at the source's `t=0`, so for the first `1.2`s both
  panels showed the same frame with nothing to blend against. Since
  GitHub displays a GIF's first frame as its static preview, this made
  the effect look absent even though it was working correctly once
  playing. Trimmed the source window to start `1.5`s in, after the blend
  already has real history, so the ghost trail is visible from frame 0.

- Rebuilt the README hero (`alpasim-demo-schema.gif`) as a diagram-above-
  footage stack instead of a side-by-side pairing: a new horizontal
  flowchart (`architecture-horizontal.svg`) banner on top, with the real
  plain-camera and motion-shadow camera panels from the dynamic-camera
  rollout below it, at native 840x430-per-panel resolution before final
  scale-down. The previous side-by-side layout (portrait diagram next to
  landscape video) forced a choice between an illegibly small diagram or
  a very wide image; stacking a wide diagram above wide video panels
  fits both aspect ratios properly. Also fixed the underlying blur from
  the original composite: render the diagram directly from SVG at the
  target size (no upscaling a smaller raster) and Lanczos-scale video
  before compositing, rather than compositing first and scaling after.
  Briefly tried a native Mermaid flowchart in place of the rasterized
  diagram, and briefly paired the diagram with the map/divergence clip
  instead of the camera panels; both were reverted in favor of this
  layout. The map/divergence clip is back as its own section below the
  hero, carrying its closed-loop-vs-log-replay claim. Also removed
  repeated content while at it: the two map-view clips (trajectory-map
  and closed-loop-divergence) merged into one, the two camera-view clips
  (plain and motion-shadow) merged into one.

- Made the README hero a schema+video pairing (`alpasim-demo-schema.gif`):
  a new vertical architecture diagram on the left, the real trajectory-map
  rollout animating on the right, so the "how it works" explanation and
  the real run are visible side by side instead of in separate sections.

- Restructured the README (hero demo, closed-loop claim, and a merged "How
  It Works" all before Install, which moved up from past the halfway point)
  and consolidated docs: merged `compatible-datasets.md` and
  `conformance.md` into `womd-targeting.md` and `cli.md` respectively, and
  folded the standalone demo-detail page back into a collapsed README
  section, going from 11 doc files to 8. Also replaced a few phrases that
  read as spoken/conversational ("that's history", "that's not a choice
  this software made") with plain declarative documentation language.

- Added a "What Real Camera And LiDAR Data Looks Like" section to
  `docs/womd-targeting.md`: two real, Apache-2.0, unmodified example
  images from `waymo-research/waymo-open-dataset` (a camera+LiDAR+3D-box
  frame, and a full LiDAR sweep with multiple boxes), the real camera and
  LiDAR position names from `dataset.proto`, and a correction/nuance on
  WOMD's newer optional sensor extensions (tokenized camera embeddings,
  not raw pixels; compressed LiDAR that does decompress to real points).
  Documented that no redistributable synchronized multi-camera sample
  exists publicly, rather than fabricating one.

- Added "Why AlpaSim, Not Waymax?" to the README's Scope section: a short,
  cited comparison (Waymax is vectorized/JAX/no camera render, per its own
  README; AlpaSim renders sensors and runs physics) explaining why they
  target different problems rather than competing for the same one.

- Added a plain-language explanation of the single-camera question with a
  labeled diagram (`camera-rig-comparison.svg`): a typical multi-camera AV
  rig (Waymo's Perception-dataset camera schema, 8 positions, cited from
  `dataset.proto`) next to this AlpaSim setup's actual one-camera rig.
  Simplified the surrounding README/design.md prose to lead with the plain
  explanation before the technical detail.

- Added `_preflight_camera_rig_compatibility`, wired into both
  `alpabridge-doctor` and `alpabridge-ready` (skip with
  `--skip-camera-rig-check`): cross-checks every public preset's declared
  cameras against the connected AlpaSim root's ego-hood rig masks and
  fails loudly, before a live session, if one asks for a camera no local
  rig provides. Traced the single-camera behavior to its root cause: the
  `hyperion_8`/`hyperion_8_1` rig assets only ever define a
  `camera_front_wide_120fov` mask, a rig-asset property, not a scene- or
  adapter-level limit. Documented in `docs/design.md`; three new tests
  cover the pass/fail/no-rig-present cases.

- Added three tests proving the adapter's camera handling is generic over
  camera count, not hardcoded to one: `predict()` and camera-set
  validation succeed with two cameras, a missing expected camera is
  rejected by name, and the frozen-camera guard correctly fires only when
  *every* declared camera stops advancing. Documented in `docs/design.md`
  and the README: every retained rollout uses one camera because that's
  the only camera any available scene reconstruction offers (checked in
  each run's `runtime.log`), not a limit in AlpaBridge itself.

- Added a real motion-shadow comparison (`alpasim-motion-shadow.gif`):
  the dynamic-camera rollout's live footage next to itself blended with
  real frames from 0.6s/1.2s earlier, showing recent camera motion as a
  visible trail directly on the footage rather than only on the map
  diagram. No synthetic geometry — real pixels from real earlier frames.

- Added a "Closed-Loop, Not Log Replay" README section with a map-only
  clip of the NAVSIM rollout showing the actually-driven path (orange)
  pulling away from the originally logged path (dashed green), captioned
  with the retained `dist_to_gt_location` / `wrong_lane` metrics —
  demonstrating what closed-loop simulation shows that log replay can't.

- Replaced the ASCII "What Closes The Loop" diagram with a hand-authored
  SVG architecture diagram, and added a "Before / After" section with a
  real, reproducible example: `scripts/render_readme_example.py` runs the
  actual shipped `route_following` preset on a synthetic input and plots
  the real trajectory it returns, next to the real input fields the
  adapter reads. Added `matplotlib` to the `viz` extra to support it.
- Swapped the README hero for a map-only crop of the NAVSIM run
  (`alpasim-trajectory-map.gif`) showing the ego's planned path curving
  through a real intersection, since the previous full-frame preview led
  with a static camera panel. The genuinely moving-camera rollout is now
  shown via its existing camera-only crop instead of the cluttered
  map+camera+metrics composite.

- Repositioned the README around engineering signal instead of research
  framing: a tested/installable/self-checking/auditable summary up top,
  the WOMD/Waymo explainer moved to `docs/womd-targeting.md` behind a
  three-line "Scope" section, the evidence table reframed as integration
  test results, and the citation demoted from a bibtex block to a one-line
  footer.
- Replaced the small cropped camera-comparison hero with two full-size,
  full-frame run previews (`alpasim-dynamic-camera-full.gif` and the
  existing `alpasim-closed-loop.gif`), each showing the live map/trajectory
  panel and the camera panel together; kept the tight side-by-side
  comparison as a collapsible detail further down.
- Rewrote the README's WOMD/Waymo section and evidence summaries in plainer
  language, and added a short "What Is WOMD?" explainer (with the Waymo
  Open Dataset logo, hot-linked and credited, and a citation to Ettinger
  et al. 2021) so readers don't need outside context for what the dataset
  actually is.
- Renamed the project from WOD2Sim to AlpaBridge (package, CLI prefix,
  env namespace, GitHub repo, and all docs), since the adapter has no real
  Waymo/WOMD dependency and the old name forced constant disclaiming.
  Frozen run evidence predating the rename keeps its original naming as a
  historical record.
- Added [compatible datasets and checkpoints](womd-targeting.md)
  documenting what's wired up today, which public datasets (nuScenes,
  nuPlan, Argoverse 2) would fit but aren't implemented, and how to
  contribute a new preset.
- Added a real AlpaSim rollout with a live `sensorsim` camera render (not a
  repeated fixture frame) and made it the README's hero preview; retained its
  evidence, manifest, and redaction log in
  `artifacts/external/alpasim_dynamic_camera_rollout/`.
- Replaced the single hero preview with a side-by-side comparison
  (`docs/assets/readme/alpasim-camera-comparison.gif`) contrasting the live
  `sensorsim` render against the public NAVSIM fixture's intentionally
  repeated frame, and tightened the surrounding README prose.
- Added a "Where To Get Each Piece" table to the README pointing to the
  Waymo Open Motion Dataset, NVIDIA AlpaSim, and Waymax.
- Focused the public branch on the AlpaSim external-driver adapter, setup and
  readiness tooling, reproducible execution, and real integration evidence.
- Added a hash-validated AlpaSim run with NAVSIM EgoStatusMLP: `197/197` finite
  outputs over `19.93` simulated seconds through the live external driver,
  controller, and physics services.
- Retained the raw camera-and-map run video, expanded configs, simulator
  results, driver telemetry, and immutable source/checkpoint hashes.
- Added deterministic reconstruction of the public fixture's declared flat
  physics surface and a telemetry-recording seed-frame video-model server.
- Added the AlpaSim E2E challenge-style external-driver package and one retained
  local conformance run.
- Clarified that AlpaBridge moves a policy interface onto AlpaSim scenes; it does
  not convert WOMD scenes into AlpaSim or make logged non-ego agents reactive.

## 0.1.0 - 2026-07-17

- Published AlpaSim adapters for `constant_velocity`, `route_following`,
  `token_dagger_bc`, and `direct_actor_planner`.
- Added setup, readiness, launch, batch, audit, summary, and support-bundle
  commands.
- Standardized runtime configuration on the `ALPABRIDGE_` environment namespace.
- Added packaged AlpaSim override files with third-party attribution.
- Added full tests, wheel smoke checks, and fresh-checkout CI coverage.
