# Reference and Claim Audit

Audit date: 2026-07-20

## Method

Every bibliography entry used by the manuscript was rechecked against an
author, publisher, proceedings, or DOI-registry record on 2026-07-20.
Search-result metadata and arXiv mirrors were not used when an official
publication record was available. Experimental claims are not delegated to
literature citations; they are linked to generated repository artifacts and
tests.

## Verified References

| Key | Primary record checked | Metadata or claim use |
| --- | --- | --- |
| `alpasim2025` | [Official AlpaSim repository and software citation](https://github.com/NVlabs/alpasim); [official `e2e_challenge` branch](https://github.com/NVlabs/alpasim/tree/e2e_challenge) | Title, official software author list, October 2025, URL, modular gRPC boundary, and evaluator branch used by WOD2Sim. |
| `ettinger2021womd` | [ICCV 2021 Open Access record](https://openaccess.thecvf.com/content/ICCV2021/html/Ettinger_Large_Scale_Interactive_Motion_Forecasting_for_Autonomous_Driving_The_Waymo_ICCV_2021_paper.html) | Authors, title, venue, pages 9710-9719. Supports the motion-dataset, road-map, interaction, and trajectory context. It replaces the perception-dataset citation previously attached to the motion-policy claim. |
| `karnchanachari2024nuplan` | [IEEE DOI record](https://doi.org/10.1109/ICRA57147.2024.10610077) | Authors, title, 2024 IEEE International Conference on Robotics and Automation, pages 629-636, and DOI. Supports characterization as a real-world learning-based planning benchmark. |
| `dosovitskiy2017carla` | [PMLR volume 78 record](https://proceedings.mlr.press/v78/dosovitskiy17a.html) | Authors, title, CoRL venue, volume 78, pages 1-16. Supports characterization as an open urban driving simulator. |
| `gulino2023waymax` | [NeurIPS 2023 proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/1838feeb71c4b4ea524d0df2f7074245-Abstract.html) | Authors, title, volume 36, Datasets and Benchmarks Track. Supports data-driven, accelerated simulation and route-guided planning context. |
| `dauner2024navsim` | [NeurIPS 2024 proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/hash/32768f7faf1995026ef9821c696f3404-Abstract-Datasets_and_Benchmarks_Track.html) | Authors, title, volume 37, track, DOI `10.52202/079017-0902`. Supports characterization as non-reactive simulation and benchmarking. |
| `dauner2024navsimbaselines` | [Official checkpoint commit](https://huggingface.co/autonomousvision/navsim_baselines/commit/32d89c0ae6e7c13c311f4a034002006c250afab0) | Commit author and date, Apache-2.0 license, the three published EgoStatusMLP seeds, and seed-0 LFS SHA-256 `87d75b0f43d077ac3531370d7cccac98656d4e9b5ce5fa6618e28b7358b3a86b`. |
| `sangiovanni2012taming` | [Publisher record](https://doi.org/10.3166/ejc.18.217-238) | Authors, journal, volume 18(3), pages 217-238, DOI. Supports contract-based design terminology. |
| `dealfaro2001interface` | [Crossref DOI record](https://doi.org/10.1145/503209.503226) | Authors, title, full joint ESEC/FSE proceedings name, pages 109-120, and DOI. Supports interface assumptions and guarantees. |
| `fremont2019scenic` | [ACM DOI record](https://doi.org/10.1145/3314221.3314633) | Authors, title, PLDI 2019, pages 63-78. Supports scenario specification and generation. |
| `dreossi2019verifai` | [Springer CAV record](https://link.springer.com/chapter/10.1007/978-3-030-25540-4_25) | Authors, title, LNCS 11561, pages 432-442, DOI. Supports simulation-based verification and falsification tooling. |
| `kim2022drivefuzz` | [Author-maintained publication page](https://drivefuzz.s3lab.io/) | Authors, title, CCS 2022, pages 1753-1767, DOI. Supports simulator-based driving-system fuzzing. |
| `wan2022planfuzz` | [Official NDSS paper](https://www.ndss-symposium.org/wp-content/uploads/2022-177-paper.pdf) | Authors, title, NDSS 2022, DOI `10.14722/ndss.2022.24177`. Supports semantic planning-vulnerability testing. |

## Claim Corrections

- The 2020 Waymo perception paper did not support the manuscript's motion-policy
  interface sentence. The manuscript now cites the 2021 Waymo Open Motion Dataset
  paper.
- AlpaSim was previously cited as corporate authorship only. The bibliography now
  follows the project's official 17-author software citation.
- Waymax and NAVSIM now cite their official NeurIPS proceedings records rather than
  arXiv mirrors; volume, track, and NAVSIM DOI metadata were added.
- The nuPlan citation now uses the peer-reviewed ICRA 2024 benchmark paper and
  DOI rather than the earlier workshop record.
- VerifAI's LNCS volume and DriveFuzz's page range were added.
- The Interface Automata entry now uses the full joint ESEC/FSE proceedings
  title from the DOI record instead of an abbreviated venue name.
- Literature citations establish related-system scope only. They do not support
  WOD2Sim's generated classification or software-timing measurements.

## Experimental Claim Sources

| Claim | Generated source | Verification |
| --- | --- | --- |
| 30-case designed diagnostic comparison | `artifacts/cvm/results/diagnostic_experiment.json` and `diagnostic_experiment_cases.csv` | `tests/test_trace_diagnostics.py` checks 15 mutations paired with 15 separately instantiated valid current-adapter sessions. |
| Label-withheld 15/15 localization | `artifacts/cvm/results/fault_injection/fault_injection.csv` | `scripts/run_cvm_matrix.py` mutates the current protocol trace, calls the detector without an expected label, and scores the result afterward. |
| Exact paired comparator counts | `classification.paired_comparison` in `diagnostic_experiment.json` | The artifact records 15 WOD2Sim-only correct and 0 status-only-only correct cases. No independence-based significance test is applied. |
| Post-parse detector execution | `timing.fault_case_detector_us` in `diagnostic_experiment.json` | 3,000 randomized, batched fault-case measurements using `time.perf_counter_ns`; parsing, I/O, and human investigation are excluded. |
| Paired adapter guard-path increment | `adapter_guard_path_timing` in `diagnostic_experiment.json` | 1,000 paired randomized measurements rotating over 15 deterministic valid adapter sessions; guarded and unchecked paths produce identical trajectories and headings. |
| Current protocol-trace provenance | `source_trace` in `diagnostic_experiment.json`; `artifacts/cvm/inputs/diagnostic_protocol_sessions.jsonl` | 15 adapter sessions contain 120 drive records, all using telemetry schema v3 and explicitly recording the current pose, every future pose, and finite serialized output. |
| Four-arm protocol replay | `artifacts/external/alpasim_protocol_replay/manifest.json` and `artifacts/cvm/results/summary.json` | Hash validation covers the official AlpaSim recording, four result/telemetry pairs, replay source files, and media. Route loss changes 56/60 route-following endpoints; all 60 NAVSIM negative-control pairs match exactly. |
| Learned checkpoint provenance | `learned_policy` in the protocol replay manifest | [Official NAVSIM baseline repository](https://huggingface.co/autonomousvision/navsim_baselines), checkpoint revision `32d89c0ae6e7c13c311f4a034002006c250afab0`, SHA-256 `87d75b0f43d077ac3531370d7cccac98656d4e9b5ce5fa6618e28b7358b3a86b`, NAVSIM source commit `0811876c274e8b058ab2be9b3dcd4d37bd23f177`, and Apache-2.0 license are pinned; the checkpoint is not redistributed. |
| External-driver conformance | `artifacts/external/alpasim_e2e_challenge_conformance/challenge-driver-fixed.jsonl` | The separate retained evaluator-owned trace records 197 drive calls but uses telemetry schema v1 without the explicit finite-output field. |

The controlled sessions and mutations are framework-authored designed cases,
not independently sampled natural faults or external simulator reruns. The
measured comparator is a completion-and-metrics gate, not another integration
framework. Timings are bounded software microbenchmarks, not end-to-end runtime
or human time-to-diagnosis.
