# Release Checklist

- [x] Paper is 4-6 A4 pages, or justified <=8-page paid version.
- [x] PDF is <=6 MB.
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
- [x] LaTeX log has no unresolved references/citations, multiply defined
  labels, or overfull/underfull `\hbox` warnings.
- [x] Every numerical paper claim maps to a generated artifact.
- [x] Failed, planned, and blocked runs are included in denominators.
- [x] Scene/policy/replicate counts are stated exactly.
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
- [x] `make cvm-eval` preserves completed evidence when rerun without `--execute`.
- [x] `pre-commit run --all-files` passes without modifying files.
- [x] Every public run manifest carries validated integration-vs-policy
  `failure_attribution`, including separate policy-behavior and policy-failure
  attribution fields.
- [x] Failure attribution requires semantic, temporal, lifecycle, deployment,
  and evidence gates before policy behavior or policy failure can be assigned.
- [x] README, paper source, run manifests, and aggregate summary are all
  validated for the integration-vs-policy attribution boundary.
- [x] README failure-attribution count snippets are validated against
  `artifacts/cvm/results/summary.json`.
- [x] Claim-evidence-matrix aggregate counts are validated against
  `artifacts/cvm/results/summary.json`.
- [x] Every public run manifest carries validated `scene` metadata and
  `scenario_category` without claiming unsupported scenario-category coverage.
- [x] `frames.csv` exposes the required public-safe frame-level schema without
  bundling restricted sensor frames or fabricating unavailable frame rows.

Current status: complete with documented limitations for the CVM paper package.
The dependency-light core rows and semantic ablation provide real closed-loop
integration evidence. Direct-actor temporal ablation and learned-policy results
remain excluded.
