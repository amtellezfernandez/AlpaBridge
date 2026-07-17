# Release Checklist

- [x] Paper is 4-6 A4 pages, or justified <=8-page paid version.
- [x] PDF is <=6 MB.
- [x] IEEE conference template is unmodified.
- [x] Author names and affiliation are retained for single-blind review.
- [x] All citations resolve in the final LaTeX build.
- [x] Every numerical paper claim maps to a generated artifact.
- [x] Failed, planned, and blocked runs are included in denominators.
- [x] Scene/policy/replicate counts are stated exactly.
- [x] No restricted assets are included.
- [x] No private paths, tokens, or credentials are present in the public scan.
- [x] Figures are generated and legible at final size.
- [x] Abstract contains actual results, not placeholders.
- [x] Abstract length is validated against the release 160-210 word range.
- [x] Limitations match actual coverage.
- [x] Reproduction commands were tested with neutral CVM targets.
- [x] Git diff was inspected.

Additional release-specific checks:

- [x] Root PDF is the only tracked manuscript PDF.
- [x] Paper source is under `paper/cvm`.
- [x] Generated evidence package is under `artifacts/cvm`.
- [x] Public artifact vocabulary uses CVM naming.
- [x] Figures and generated tables carry the aggregate data hash.
- [x] `make cvm-eval` preserves completed evidence when rerun without `--execute`.
- [x] `pre-commit run --all-files` passes without modifying files.
- [x] Every public run manifest carries validated integration-vs-policy
  `failure_attribution`, including separate policy-behavior and policy-failure
  attribution fields.
- [x] Failure attribution requires semantic, temporal, lifecycle, deployment,
  and evidence gates before policy behavior or policy failure can be assigned.
- [x] Every public run manifest carries validated `scene` metadata and
  `scenario_category` without claiming unsupported scenario-category coverage.
- [x] `frames.csv` exposes the required public-safe frame-level schema without
  bundling restricted sensor frames or fabricating unavailable frame rows.

Current status: complete with documented limitations for the CVM paper artifact.
The dependency-light core rows and semantic ablation provide real closed-loop
integration evidence. Direct-actor temporal ablation and learned-policy results
remain excluded.
