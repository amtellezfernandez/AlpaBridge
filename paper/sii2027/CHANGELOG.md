# SII 2027 Paper Changelog

## 2026-07-17

- Created the SII 2027 paper workspace.
- Added public inventory and baseline reports under `artifacts/sii2027/reports/`.
- Added SII configs, matrix expansion, aggregation, generated tables, and generated figures.
- Added a buildable IEEEtran A4 draft in `main.tex` using the CTAN IEEEtran class copied
  into the paper directory because TeX Live did not provide `IEEEtran.cls`; only trailing
  whitespace was normalized for repository hygiene.
- Built root-level `wod2sim.pdf` as the canonical A4 paper draft whose claims are
  limited to configured/blocked SII rows.
- Preserved the claim boundary: no closed-loop SII result, ablation result, lifecycle-stress result,
  or fault-localization result is reported as completed.
- Added a repository artifact-map appendix so the paper remains connected to the
  WOD2Sim source tree rather than appearing as a detached SII package.
