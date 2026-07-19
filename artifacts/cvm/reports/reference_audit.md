# Reference and Claim Audit

Audit date: 2026-07-19

## Method

Every bibliography entry used by the manuscript was checked against an author,
publisher, proceedings, or DOI record. Search-result metadata and arXiv mirrors were
not used when an official publication record was available. Experimental claims are
not delegated to literature citations; they are linked to generated repository
artifacts and tests.

## Verified References

| Key | Primary record checked | Metadata or claim use |
| --- | --- | --- |
| `alpasim2025` | [Official AlpaSim repository and software citation](https://github.com/NVlabs/alpasim) | Title, 17-author software citation, October 2025, URL. The repository documents the external driver and modular simulator boundary used by WOD2Sim. |
| `ettinger2021womd` | [ICCV 2021 Open Access record](https://openaccess.thecvf.com/content/ICCV2021/html/Ettinger_Large_Scale_Interactive_Motion_Forecasting_for_Autonomous_Driving_The_Waymo_ICCV_2021_paper.html) | Authors, title, venue, pages 9710-9719. Supports the motion-dataset, road-map, interaction, and trajectory context. It replaces the perception-dataset citation previously attached to the motion-policy claim. |
| `caesar2021nuplan` | [Official nuScenes/nuPlan publications page](https://www.nuscenes.org/publications) | Title, authors, and CVPR 2021 ADP3 Workshop venue. Supports characterization as a closed-loop planning benchmark. |
| `dosovitskiy2017carla` | [PMLR volume 78 record](https://proceedings.mlr.press/v78/dosovitskiy17a.html) | Authors, title, CoRL venue, volume 78, pages 1-16. Supports characterization as an open urban driving simulator. |
| `gulino2023waymax` | [NeurIPS 2023 proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/1838feeb71c4b4ea524d0df2f7074245-Abstract.html) | Authors, title, volume 36, Datasets and Benchmarks Track. Supports data-driven, accelerated simulation and route-guided planning context. |
| `dauner2024navsim` | [NeurIPS 2024 proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/hash/32768f7faf1995026ef9821c696f3404-Abstract-Datasets_and_Benchmarks_Track.html) | Authors, title, volume 37, track, DOI `10.52202/079017-0902`. Supports characterization as non-reactive simulation and benchmarking. |
| `sangiovanni2012taming` | [Publisher record](https://doi.org/10.3166/ejc.18.217-238) | Authors, journal, volume 18(3), pages 217-238, DOI. Supports contract-based design terminology. |
| `dealfaro2001interface` | [Crossref DOI record](https://doi.org/10.1145/503209.503226) | Authors, title, ESEC/FSE venue, pages 109-120, proceedings DOI. Supports interface assumptions and guarantees. |
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
- VerifAI's LNCS volume and DriveFuzz's page range were added.
- Literature citations establish related-system scope only. They do not support the
  WOD2Sim accuracy, diagnosis-latency, or guard-overhead results.

## Experimental Claim Sources

| Claim | Generated source | Verification |
| --- | --- | --- |
| 30-case controlled diagnostic comparison | `artifacts/cvm/results/diagnostic_experiment.json` and `diagnostic_experiment_cases.csv` | `tests/test_trace_diagnostics.py` checks all 15 mutations and all 15 valid controls. |
| Independent 15/15 localization | `artifacts/cvm/results/fault_injection/fault_injection.csv` | `scripts/run_cvm_matrix.py` mutates the retained trace, calls the detector without an expected label, and scores the result afterward. |
| Exact paired comparator test | `classification.paired_mcnemar` in `diagnostic_experiment.json` | Exact two-sided McNemar/binomial calculation is tested against `2 / 2^15`. |
| Post-trace diagnosis latency | `timing.correct_fault_diagnosis_us` in `diagnostic_experiment.json` | 3,000 randomized, batched fault-case measurements using `time.perf_counter_ns`. |
| Online guard overhead | `online_guard_overhead` in `diagnostic_experiment.json` | 200 paired randomized iterations; guarded and unchecked paths produce identical trajectories. |
| External-driver latency context | `source_trace` in `diagnostic_experiment.json` | Derived from 197 retained drive calls in the hashed external AlpaSim trace. |

The controlled mutations are framework-authored and applied offline to one retained
external-driver trace. The measured comparator is a completion-and-metrics status
gate, not a claim about every external integration framework.
