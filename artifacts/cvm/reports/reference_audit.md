# Reference And Claim Audit

Audit date: 2026-07-20

## Method

Every bibliography entry used by the manuscript was rechecked against an
author, publisher, proceedings, project, or DOI-registry record on 2026-07-20.
Search-result metadata and arXiv mirrors were not used when an official
publication record was available. The audit covers title, author list, year,
venue, pages where assigned, DOI, and cited software revision. Experimental
claims are not delegated to literature citations; they are linked to generated
repository artifacts and tests below.

## Verified References

| Key | Primary record checked | Metadata or claim use |
| --- | --- | --- |
| `alpasim2025` | [Official AlpaSim repository and software citation](https://github.com/NVlabs/alpasim); [official `e2e_challenge` branch](https://github.com/NVlabs/alpasim/tree/e2e_challenge) | Software title, official author list, October 2025 date, URL, modular gRPC boundary, and evaluator branch used by WOD2Sim. |
| `ettinger2021womd` | [ICCV 2021 Open Access record](https://openaccess.thecvf.com/content/ICCV2021/html/Ettinger_Large_Scale_Interactive_Motion_Forecasting_for_Autonomous_Driving_The_Waymo_ICCV_2021_paper.html) | Authors, title, venue, and pages 9710-9719. Supports the motion-dataset, road-map, interaction, and trajectory context. |
| `karnchanachari2024nuplan` | [IEEE DOI record](https://doi.org/10.1109/ICRA57147.2024.10610077) | Authors, title, ICRA 2024, pages 629-636, and DOI. Supports characterization as a real-world learning-based planning benchmark. |
| `dosovitskiy2017carla` | [PMLR volume 78 record](https://proceedings.mlr.press/v78/dosovitskiy17a.html) | Authors, title, CoRL venue, volume 78, year, and pages 1-16. Supports characterization as an open urban driving simulator. |
| `gulino2023waymax` | [NeurIPS 2023 proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/1838feeb71c4b4ea524d0df2f7074245-Abstract.html) | Authors, title, volume 36, Datasets and Benchmarks Track, and year. Supports characterization as accelerated data-driven simulation. |
| `dauner2024navsim` | [NeurIPS 2024 proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/hash/32768f7faf1995026ef9821c696f3404-Abstract-Datasets_and_Benchmarks_Track.html) | Authors, title, volume 37, track, year, and DOI `10.52202/079017-0902`. Supports characterization as non-reactive simulation and benchmarking. |
| `dauner2024navsimbaselines` | [Official checkpoint commit](https://huggingface.co/autonomousvision/navsim_baselines/commit/32d89c0ae6e7c13c311f4a034002006c250afab0) | Commit author and date, Apache-2.0 label, published EgoStatusMLP seeds, and the seed-0 LFS SHA-256 used by the artifact manifest. |
| `sangiovanni2012taming` | [Publisher DOI record](https://doi.org/10.3166/ejc.18.217-238) | Authors, title, journal, volume 18(3), pages 217-238, year, and DOI. Supports contract-based design terminology. |
| `dealfaro2001interface` | [ACM DOI record](https://doi.org/10.1145/503209.503226) | Authors, title, full joint ESEC/FSE proceedings name, pages 109-120, year, and DOI. Supports interface assumptions and guarantees. |
| `fremont2019scenic` | [ACM DOI record](https://doi.org/10.1145/3314221.3314633) | Authors, title, PLDI 2019, pages 63-78, and DOI. Supports scenario specification and generation. |
| `dreossi2019verifai` | [Springer CAV record](https://link.springer.com/chapter/10.1007/978-3-030-25540-4_25) | Authors, title, CAV 2019, LNCS 11561, pages 432-442, and DOI. Supports simulation-based verification and falsification tooling. |
| `kim2022drivefuzz` | [Author-maintained publication page](https://drivefuzz.s3lab.io/) | Authors, title, CCS 2022, pages 1753-1767, and DOI `10.1145/3548606.3560558`. Supports simulator-based driving-system fuzzing. |
| `wan2022planfuzz` | [NDSS DOI record](https://doi.org/10.14722/ndss.2022.24177) | Authors, title, NDSS 2022, and DOI. Supports semantic planning-vulnerability testing. |

## Claim Corrections

- The 2020 Waymo perception paper did not support the manuscript's
  motion-policy interface sentence. The manuscript uses the 2021 Waymo Open
  Motion Dataset paper instead.
- AlpaSim was previously cited as corporate authorship only. The bibliography
  now follows the project's official 17-author software citation.
- Waymax and NAVSIM use their official NeurIPS proceedings records rather than
  arXiv mirrors; volume, track, and NAVSIM DOI metadata are included.
- The nuPlan entry uses the peer-reviewed ICRA 2024 benchmark paper and DOI
  rather than the earlier workshop record.
- VerifAI's LNCS volume and DriveFuzz's page range are present.
- The Interface Automata entry uses the full joint ESEC/FSE proceedings title
  from the DOI record instead of an abbreviated venue name.
- Literature citations establish related-system scope only. They do not
  support WOD2Sim's generated classification, behavior, or timing results.

## Experimental Claim Sources

| Claim | Generated source | Verification |
| --- | --- | --- |
| Waymax/WOMD policy-by-route interaction | `artifacts/external/waymax_contract_study/results-summary.json`, `scenario-results.jsonl`, and `manifest.json` | The manifest pins Waymax commit `a64dfec9be8576b60d9cecc94f406d9812d4a7d0`, the official fixture SHA-256, implementation hashes, and result hashes. `tests/test_waymax_contract_study.py` recomputes the 20-scenario summary, 19 eligible pairs, route-following divergence, exact constant-velocity invariance, and signature-dependent audit. |
| 30-case designed diagnostic comparison | `artifacts/cvm/results/diagnostic_experiment.json` and `diagnostic_experiment_cases.csv` | `tests/test_trace_diagnostics.py` checks 15 mutations paired with 15 separately instantiated valid current-adapter sessions. |
| Label-withheld 15/15 localization | `artifacts/cvm/results/fault_injection/fault_injection.csv` | `scripts/run_cvm_matrix.py` mutates the current protocol trace, calls the detector without an expected label, and scores the result afterward. |
| Exact paired comparator counts | `classification.paired_comparison` in `diagnostic_experiment.json` | The artifact records 15 WOD2Sim-only correct and 0 status-only-only correct cases. No independence-based significance test is applied. |
| Post-parse detector execution | `timing.fault_case_detector_us` in `diagnostic_experiment.json` | 3,000 randomized, batched fault-case measurements use `time.perf_counter_ns`; parsing, I/O, and human investigation are excluded. |
| Paired adapter guard-path increment | `adapter_guard_path_timing` in `diagnostic_experiment.json` | 1,000 paired randomized measurements rotate over 15 deterministic valid adapter sessions; guarded and unchecked paths produce identical trajectories and headings. |
| Current protocol-trace provenance | `source_trace` in `diagnostic_experiment.json`; `artifacts/cvm/inputs/diagnostic_protocol_sessions.jsonl` | Fifteen adapter sessions contain 120 drive records, use telemetry schema v3, and explicitly record the current pose, every future pose, and finite serialized output. |
| Four-arm protocol replay | `artifacts/external/alpasim_protocol_replay/manifest.json` and `artifacts/cvm/results/summary.json` | Hash validation covers the official AlpaSim recording, four result/telemetry pairs, replay source files, and media. Route loss changes 56/60 route-following endpoints; all 60 NAVSIM negative-control pairs match exactly. |
| Learned checkpoint provenance | `learned_policy` in the protocol replay manifest | The official NAVSIM baseline checkpoint revision `32d89c0ae6e7c13c311f4a034002006c250afab0`, LFS SHA-256, NAVSIM source commit, and Apache-2.0 license are pinned; the checkpoint is not redistributed. |
| Reactive learned external-driver rollout | `artifacts/external/alpasim_navsim_reactive_rollout/manifest.json`, telemetry, AlpaSim result, logs, and raw MP4 | The aggregate and validator hash-check every retained file. One rollout passes with 197/197 finite learned outputs, 198 live render requests, and 19.93 simulated seconds. Its repeated camera seed and declared flat surface bound the claim to camera-blind lifecycle and exact-configuration timing. |
| External-driver conformance | `artifacts/external/alpasim_e2e_challenge_conformance/challenge-driver-fixed.jsonl` | The separate retained evaluator-owned trace records 197 drive calls but uses telemetry schema v1 without the explicit finite-output field. |

The controlled sessions and mutations are framework-authored designed cases,
not independently sampled natural faults or external simulator reruns. The
Waymax fixture is complete for the pinned upstream test file but is not a
representative WOMD sample. The measured comparator is a
completion-and-metrics gate, not another integration framework. Timings are
bounded software measurements, not end-to-end runtime overhead or human
time-to-diagnosis evidence.
