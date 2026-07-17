# SII 2027 Blockers

## Manuscript And Template

- Legacy manuscript `paper/paper.pdf` remains 9 pages and Letter-sized.
- SII draft `paper/sii2027/paper.pdf` now builds as an IEEEtran A4 PDF with 4 pages and a size below 6 MB.
- `IEEEtran.cls` was not installed by TeX Live, so the CTAN IEEEtran class was copied locally into `paper/sii2027/IEEEtran.cls`; only trailing whitespace was normalized for repository hygiene.
- `pdfinfo`, `pdffonts`, `qpdf`, and `latexmk` are unavailable. Validation currently uses `mutool` and source/log checks as fallbacks, so the requested `pdffonts`/`qpdf` checks remain unavailable in this environment.

## Runtime And Experiment Execution

- The SII runner now executes public synthetic lifecycle/fault matrices behind `--execute`.
- The SII runner now materializes per-row closed-loop readiness and launch plans in
  `artifacts/sii2027/manifests/run_manifests/`. Supported full-contract rows have
  exact `run_alpasim_local_external` commands; unsupported ablation rows record
  `command: null` plus the reason.
- A one-scene local readiness probe passed for the configured 26.02 local USDZ
  cache, Docker access, GPU runtime, local image, and AlpaSim virtualenv. This
  removes the earlier `all-usdzs`/`HF_TOKEN` ambiguity for the selected local
  cache path.
- Default `make sii2027-eval` still does not launch real rollouts. Passing
  `--execute` is required for supported full-contract closed-loop rows.
- `direct_actor_planner` rows are blocked until an oracle actor-proxy JSON is generated and recorded.
- `command_only_route` semantic-ablation rows are blocked because no runtime-safe
  adapter flag currently switches the launcher into that ablated behavior.
- `token_dagger_bc` is intentionally excluded from the core matrix because no legitimate local checkpoint hash is established and Torch is unavailable.
- Scene categories are unverified. Six locally cached 26.02 front-camera scenes are selected by availability, but no authoritative metadata currently proves the required straight/turn/lane-change/dense-traffic/occlusion/merge taxonomy.
- AlpaSim worktrees are dirty and should be audited before treating them as immutable simulator state.

## Evidence And Claims

- SII matrices: 145 configured rows, 55 attempted/completed public synthetic rows, 90 blocked closed-loop scene rows.
- Current blocked counts: 45 `execution_not_requested` rows, 36
  `direct_actor_oracle_proxy_missing` rows, and 9
  `semantic_ablation_runtime_flag_missing` rows.
- Fault injectors execute in a deterministic public synthetic harness: 15/15 detected and localized; not claim-valid closed-loop evidence.
- Lifecycle stress executes in a deterministic public synthetic harness: 20/20 hardened cycles survived and 0/20 strict/pre-hardening cycles survived; not claim-valid closed-loop evidence.
- No behavioral metrics from SII closed-loop runs exist yet.
- The SII paper may claim configured/blocked closed-loop counts and public synthetic diagnostics only. It must not claim policy performance, real-scene ablation effects, or simulator-backed lifecycle/fault reliability.

## Baseline Quality Gates

- `pytest -q`, `make conformance`, `make demo`, `ruff check`, and package build passed.
- `pre-commit run --all-files` failed because `ruff-format` would reformat 43 existing files. Those formatting changes were discarded as unrelated to this objective.
