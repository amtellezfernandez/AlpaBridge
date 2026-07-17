# SII 2027 Paper Changelog

## 2026-07-17

- Created the SII 2027 paper workspace.
- Added Phase A inventory and baseline reports under `artifacts/sii2027/reports/`.
- Added SII configs, matrix expansion, aggregation, generated tables, and generated figures.
- Added a buildable IEEEtran A4 draft in `main.tex` using the CTAN IEEEtran class copied
  into the paper directory because TeX Live did not provide `IEEEtran.cls`; only trailing
  whitespace was normalized for repository hygiene.
- Built `paper.pdf` as a 4-page A4 draft whose claims are limited to configured/blocked SII rows.
- Preserved the claim boundary: no closed-loop SII result, ablation result, lifecycle-stress result,
  or fault-localization result is reported as completed.
