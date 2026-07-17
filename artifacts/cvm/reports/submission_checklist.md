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
- [ ] `pre-commit run --all-files` passes without modifying files.

Current status: complete with documented limitations for the CVM paper draft.
The dependency-light core rows and semantic ablation provide real closed-loop
integration evidence. Direct-actor temporal ablation and learned-policy results
remain excluded. The configured pre-commit formatting hook is the only failed
auxiliary gate; applying it would introduce a broad unrelated formatting diff.
