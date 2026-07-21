# Changelog

All notable adapter-release changes are tracked here.

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
