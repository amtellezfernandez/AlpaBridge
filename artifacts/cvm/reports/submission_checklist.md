# Release Checklist

The contract-validation matrix (CVM) is the release evidence surface referenced
in this checklist.

- [x] Target-venue author instructions were rechecked on 2026-07-20: regular
  papers are single-blind, 4-6 A4 pages, a single PDF no larger than 6 MB, and
  submitted through PaperPlaza; the listed regular-paper deadline is
  2026-08-07.
- [x] Paper is 4-6 A4 pages, or justified <=8-page paid version.
- [x] PDF is <=6 MB.
- [x] Optional camera-comparison video is an H.264 MP4 under the venue's
  10 MB attachment limit (`docs/assets/readme/alpasim-protocol-replay.mp4`,
  470,872 bytes); all labels are outside the camera panels.
- [x] PDF MediaBox is parsed and validated as portrait A4.
- [x] PDF fonts are embedded according to the `mutool` descriptor validation.
- [x] IEEE conference template is unmodified.
- [x] Paper source has no manual margin, page-style, font-scaling, or negative
  spacing overrides.
- [x] Author names and affiliation are retained for single-blind review.
- [x] Title, author, affiliation, PDF subject, and abstract hash match
  `paper/cvm/metadata.json`.
- [x] Generated PDF title, author, and subject metadata match
  `paper/cvm/metadata.json`.
- [x] Python package metadata exposes author, README, BSD-3-Clause license
  expression, research keywords, and paper/docs/citation URLs.
- [x] CI enforces package, conformance, coverage, smoke, wheel-install,
  paper-validation, PDF-structure, artifact-upload, and minimal-permission
  gates.
- [x] All citations resolve in the final LaTeX build.
- [x] Bibliography metadata and claim-to-source alignment are checked against
  primary publication or author records in `reference_audit.md`.
- [x] LaTeX log has no unresolved references/citations, multiply defined
  labels, or overfull/underfull `\hbox` warnings.
- [x] Every numerical paper claim maps to a generated artifact.
- [x] Failed, planned, and blocked runs are included in denominators.
- [x] Scene/policy/execution counts are stated exactly.
- [x] No restricted assets are included.
- [x] No private paths, tokens, or credentials are present in the public scan.
- [x] Public Markdown/HTML local links and image references resolve inside the
  repository.
- [x] Public Markdown/HTML images carry non-empty alt text.
- [x] `docs/cli.md` documents every console script and `.PHONY` Make target.
- [x] README visuals explain the adapter boundary, runtime graph meanings, and
  non-benchmark status.
- [x] Evaluation docs distinguish completed local diagnostic closed-loop rows
  from public policy benchmark evidence.
- [x] GitHub contribution, pull-request, issue, and security templates preserve
  the claim boundary and restricted-asset hygiene.
- [x] Public release text excludes venue-style benchmark labels.
- [x] Public release text excludes unstable generated citation slugs.
- [x] Figures are generated and legible at final size.
- [x] Abstract contains actual results, not placeholders.
- [x] Abstract length is validated against the release 160-210 word range.
- [x] Limitations match actual coverage.
- [x] Reproduction commands were tested with CVM targets.
- [x] Git diff was inspected.

Additional release-specific checks:

- [x] Root PDF is the only tracked manuscript PDF.
- [x] Paper source is under `paper/cvm`.
- [x] Generated evidence package is under `artifacts/cvm`.
- [x] Public artifact vocabulary uses CVM naming.
- [x] Figures and generated tables carry the aggregate data hash.
- [x] Paper-side generated tables and figures are byte-identical to the
  canonical CVM artifacts.
- [x] Generated table row values are validated against `summary.json`,
  `lifecycle_stress.csv`, and `fault_injection.csv` source fields.
- [x] `paper_numbers.tex` macros are validated against `summary.json`,
  `lifecycle_stress.csv`, and `fault_injection.csv`.
- [x] Diagnostic case, comparator, and timing macros are validated
  against the tracked diagnostic experiment in `summary.json`.
- [x] Matrix and aggregate `created_at` timestamps are validated against
  run-manifest evidence timestamps so paper rebuilds do not drift on wall-clock
  time alone.
- [x] `make cvm-eval` preserves completed evidence when rerun without `--execute`.
- [x] `pre-commit run --all-files` passes without modifying files.
- [x] Every public run manifest carries validated pre-audit
  integration-vs-policy `failure_attribution`, including separate
  policy-behavior and policy-failure attribution fields.
- [x] Failure attribution requires semantic, temporal, lifecycle, deployment,
  and evidence gates before policy behavior or policy failure can be assigned.
- [x] README, paper source, run manifests, and aggregate summary are all
  validated for the integration-vs-policy attribution boundary.
- [x] README failure-attribution count snippets are validated against
  `artifacts/cvm/results/summary.json`.
- [x] Claim-evidence-matrix aggregate counts are validated against
  `artifacts/cvm/results/summary.json`.
- [x] Contract-test audit report is validated for semantic, temporal,
  lifecycle, deployment/plugin-dependency, evidence, fault-injection, and
  explicit-gap coverage.
- [x] Every public run manifest carries validated `scene` metadata and
  `scenario_category` without claiming unsupported scenario-category coverage.
- [x] Aggregate scenario coverage reports 0/6 verified required categories and
  15 unclassified closed-loop scenes, so no unsupported coverage claim is made.
- [x] `frames.csv` exposes the required public-safe frame-level schema without
  bundling restricted sensor frames or fabricating unavailable frame rows.

Scientific-readiness checks:

- [x] Evaluate at least one learned policy checkpoint through the complete
  contract stack. One camera-blind NAVSIM rollout completes 197/197 finite
  outputs; static pixels and flat ground bound it to lifecycle evidence.
- [x] Compare descriptively against an executable status-only gate and measure
  post-parse detector execution plus guarded and unchecked in-process adapter
  Drive paths with a paired guard-path increment.
- [ ] Compare against a complete independently maintained integration
  framework or a human debugging workflow.
- [ ] Repeat scene-policy trials with controlled seeds and report uncertainty.
- [ ] Verify coverage of the six required scenario categories.
- [ ] Complete the direct-actor temporal-ablation matrix.
- [ ] Publish sufficient scene identifiers and frame-level evidence for an
  authorized evaluator to replay the reported trials.

Current status: the PDF and release package are mechanically ready. The
controlled mutation study supplies an executable comparator, localization,
false-positive controls, exact paired counts, post-parse detector timing, and a
guarded in-process adapter Drive-path measurement with a paired guard-path
increment. It does not claim population inference,
end-to-end runtime, or human time-to-diagnosis. Scientific scope remains
contract conformance because the package
does not include a learned-policy quality evaluation, external full-framework
comparator, replicated scene trials, verified scenario coverage, direct-actor
temporal ablation, responsive camera rendering, or unrestricted replay assets.
