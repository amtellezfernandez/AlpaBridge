from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_cvm_submission.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_cvm_submission", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_ci_workflow_fixture() -> str:
    return (
        "on:\n"
        "  push:\n"
        '    branches: ["main"]\n'
        "  pull_request:\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "\n"
        "jobs:\n"
        "  package:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v6\n"
        "      - uses: actions/setup-python@v6\n"
        "      - uses: astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39\n"
        "      - run: uv sync --extra dev\n"
        "      - run: make lint PYTHON='uv run python'\n"
        "      - run: make conformance PYTHON='uv run python'\n"
        "      - run: make coverage PYTHON='uv run python'\n"
        "      - run: make smoke PYTHON='uv run python'\n"
        "      - run: uv run python -m build\n"
        "      - run: uv run alpabridge-doctor --strict-installed --json\n"
        "      - run: alpabridge-build-oracle-proxy --help\n"
        "      - run: alpabridge-batch --mode print\n"
        "      - uses: actions/upload-artifact@v7\n"
        "  paper:\n"
        "    steps:\n"
        "      - run: make paper-verify PYTHON='uv run python'\n"
        "      - run: qpdf --check alpabridge.pdf\n"
        "      - run: pdfinfo alpabridge.pdf\n"
        "      - run: pdffonts alpabridge.pdf\n"
    )


def _write_paper_number_fixture(root: Path, module) -> tuple[Path, Path, Path, Path]:
    summary = {
        "total_rows": 10,
        "planned_runs": 0,
        "attempted_runs": 8,
        "completed_runs": 7,
        "synthetic_completed_runs": 3,
        "closed_loop_completed_runs": 4,
        "closed_loop_audit_valid_runs": 3,
        "closed_loop_metric_rows": 4,
        "failed_runs": 1,
        "blocked_runs": 2,
        "integration_effectiveness": {
            "full_contract_completed_runs": 3,
            "full_contract_audit_valid_runs": 3,
            "semantic_ablation_completed_pairs": 2,
            "semantic_ablation_comparison_eligible_pairs": 2,
            "semantic_ablation_command_proxy_completed_runs": 2,
            "semantic_ablation_command_proxy_metric_runs": 2,
            "semantic_ablation_command_proxy_rejected_runs": 2,
            "status_only_baseline_accepted_runs": 2,
            "status_only_baseline_acceptance_denominator": 2,
            "contract_invalid_evidence_rejected_runs": 2,
            "contract_invalid_evidence_rejection_denominator": 2,
            "status_only_accepted_contract_rejected_runs": 2,
        },
        "scenario_coverage": {
            "closed_loop_scene_count": 4,
            "required_category_count": 6,
            "verified_required_category_count": 0,
            "unclassified_closed_loop_scene_count": 4,
            "scenario_category_coverage_claimed": False,
            "scenario_category_coverage_claimed_int": 0,
        },
        "failure_attribution": {
            "contract_valid_closed_loop_rows": 3,
            "integration_or_evidence_invalid_closed_loop_rows": 1,
            "claim_valid_policy_benchmark_rows": 0,
            "policy_behavior_attributable_rows": 3,
            "policy_failure_attributable_rows": 0,
            "integration_failure_attributable_rows": 2,
            "diagnostic_not_policy_rows": 4,
            "non_policy_attributed_rows": 7,
            "synthetic_diagnostic_rows": 3,
        },
        "release_scope": {
            "public_core_configured_rows": 3,
            "public_core_attempted_runs": 3,
            "public_core_completed_runs": 3,
            "public_core_audit_valid_runs": 3,
            "public_core_blocked_rows": 0,
            "optional_gated_configured_rows": 2,
            "optional_gated_blocked_rows": 2,
            "direct_actor_configured_rows": 2,
            "direct_actor_blocked_rows": 2,
        },
        "semantic_ablation_deltas": {
            "progress": {"mean_delta_full_minus_command_only": -0.25},
            "progress_rel": {"mean_delta_full_minus_command_only": 0.125},
            "offroad": {"mean_delta_full_minus_command_only": 0.0},
            "collision_any": {"mean_delta_full_minus_command_only": 0.333333},
            "plan_deviation": {"mean_delta_full_minus_command_only": 0.5},
        },
        "closed_loop_metrics": {
            "collision_any": {"mean": 0.75},
            "offroad": {"mean": 0.0},
            "progress": {"mean": 0.4},
        },
        "external_compatibility": {
            "rollouts": 1,
            "passed_rollouts": 1,
            "drive_rpc_count": 197,
            "image_event_count": 396,
            "latency_target_met_count": 197,
            "latency_target_denominator": 197,
            "driver_latency_mean_ms": 2.135,
            "driver_latency_max_ms": 11.966,
        },
        "navsim_reactive_rollout": {
            "rollouts": 1,
            "passed_rollouts": 1,
            "drive_rpc_count": 197,
            "finite_drive_outputs": 197,
            "latency_target_met_count": 197,
            "camera_event_count": 198,
            "render_call_count": 198,
            "internal_driver_latency_ms": {
                "p50": 1.982387,
                "p95": 3.3624532,
            },
            "service_drive_rpc": {
                "mean_ms": 3.205829152,
            },
            "runtime": {
                "simulated_s": 19.93,
                "active_wall_clock_s": 16.51,
                "total_wall_clock_s": 18.90,
            },
            "behavior_metrics_not_used_as_policy_quality_claims": {
                "dist_traveled_m": 61.863193356,
                "wrong_lane": 1.0,
            },
            "negative_control": {
                "drive_calls_before_rejection": 4,
            },
        },
        "protocol_replay": {
            "policy_family_count": 2,
            "media": {"camera_frames": 60},
            "trajectory_divergence": {
                "route_following": {
                    "endpoint_difference_gt_0_1m": 56,
                },
                "navsim_ego_status_mlp": {
                    "endpoint_difference_gt_0_1m": 0,
                    "endpoint_difference_gt_1m": 0,
                    "endpoint_difference_mean_m": 0.0,
                    "endpoint_difference_max_m": 0.0,
                },
            },
            "arms": {
                "full_contract": {
                    "diagnostic_count": 0,
                    "drive_calls": 60,
                    "finite_drive_outputs": 60,
                    "nonstationary_drive_outputs": 60,
                    "drive_calls_within_target": 60,
                    "drive_rpc_latency_ms": {
                        "p50": 1.786,
                        "p95": 2.191,
                    },
                },
                "command_only_route": {
                    "diagnostic_count": 1,
                    "drive_calls": 60,
                    "finite_drive_outputs": 60,
                    "nonstationary_drive_outputs": 60,
                    "drive_calls_within_target": 60,
                    "drive_rpc_latency_ms": {
                        "p50": 1.835,
                        "p95": 2.338,
                    },
                },
                "navsim_ego_status_mlp_full_contract": {
                    "diagnostic_count": 0,
                    "drive_calls": 60,
                    "finite_drive_outputs": 60,
                    "nonstationary_drive_outputs": 60,
                    "drive_calls_within_target": 60,
                    "drive_rpc_latency_ms": {
                        "p50": 7.194,
                        "p95": 8.477,
                    },
                },
                "navsim_ego_status_mlp_command_only_route": {
                    "diagnostic_count": 0,
                    "drive_calls": 60,
                    "finite_drive_outputs": 60,
                    "nonstationary_drive_outputs": 60,
                    "drive_calls_within_target": 60,
                    "drive_rpc_latency_ms": {
                        "p50": 6.750,
                        "p95": 8.028,
                    },
                },
            },
        },
        "waymax_contract_study": {
            "behavior": {
                "scenario_count": 20,
                "comparison_eligible_scenarios": 19,
                "route_unavailable_scenarios": 1,
                "closed_loop_steps_total": 3800,
                "finite_trajectory_plans": 3800,
                "negative_control_invariant_scenarios": 19,
                "endpoint_difference_m": {
                    "route_following": {
                        "mean": 1.972612,
                        "median": 1.017287,
                        "max": 14.210695,
                        "changed_count": 13,
                        "material_change_count": 10,
                    },
                    "constant_velocity": {
                        "max": 0.0,
                    },
                },
                "difference_in_differences_endpoint_m": {
                    "mean": 1.972612,
                    "median": 1.017287,
                },
                "attribution": {
                    "route_following_full_route_clean": 19,
                    "route_following_command_proxy_semantic_fault": 19,
                    "constant_velocity_full_route_clean": 19,
                    "constant_velocity_command_proxy_clean": 19,
                },
            },
        },
        "diagnostic_experiment": {
            "design": {
                "total_cases": 30,
                "fault_cases": 15,
                "control_cases": 15,
            },
            "classification": {
                "alpabridge": {
                    "classification_correct": 30,
                    "faults_detected": 15,
                    "faults_correctly_localized": 15,
                    "false_positives": 0,
                },
                "status_only": {
                    "classification_correct": 15,
                    "faults_detected": 0,
                    "false_positives": 0,
                },
                "paired_comparison": {
                    "discordant_pairs": 15,
                },
            },
            "timing": {
                "contract_gate_decision_us": {
                    "p50": 186.125,
                    "p95": 240.500,
                },
                "fault_case_detector_us": {
                    "p50": 205.750,
                    "p95": 260.250,
                },
            },
            "adapter_guard_path_timing": {
                "input_cases": 15,
                "guarded_drive_path_us": {
                    "p50": 125.750,
                    "p95": 180.250,
                },
                "paired_incremental_us": {
                    "p50": 23.125,
                    "p95": 35.500,
                    "samples": 1000,
                },
            },
            "source_trace": {
                "session_count": 15,
                "drive_count": 120,
                "explicit_finite_drive_count": 120,
            },
        },
        "core_policy_results": [
            {
                "policy": "constant_velocity",
                "configured_rows": 4,
                "attempted_runs": 3,
                "completed_runs": 3,
                "audit_valid_runs": 3,
                "route_valid_runs": 3,
                "sensor_valid_runs": 3,
                "metric_rows": 3,
                "blocked_runs": 1,
                "progress_mean": 0.4,
                "collision_any_mean": 0.75,
                "offroad_mean": 0.0,
                "action_latency_p95_ms": None,
                "service_crash_rows": 0,
            }
        ],
        "public_core_policy_results": [
            {
                "policy": "constant_velocity",
                "configured_rows": 4,
                "attempted_runs": 3,
                "completed_runs": 3,
                "audit_valid_runs": 3,
                "route_valid_runs": 3,
                "sensor_valid_runs": 3,
                "metric_rows": 3,
                "blocked_runs": 1,
                "progress_mean": 0.4,
                "collision_any_mean": 0.75,
                "offroad_mean": 0.0,
                "action_latency_p95_ms": None,
                "service_crash_rows": 0,
            }
        ],
        "matrix_counts": {
            "core": 4,
            "semantic_ablation": 2,
            "temporal_ablation": 1,
            "lifecycle_stress": 3,
            "fault_injection": 2,
        },
    }
    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    lifecycle_path = root / "lifecycle_stress.csv"
    lifecycle_path.write_text(
        "adapter_config,service_survived\n"
        "full_lifecycle_hardening,true\n"
        "full_lifecycle_hardening,false\n"
        "strict_or_pre_hardening_behavior,false\n",
        encoding="utf-8",
    )
    fault_path = root / "fault_injection.csv"
    fault_path.write_text(
        "detected,correctly_localized\ntrue,true\nfalse,false\n",
        encoding="utf-8",
    )
    macro_values: dict[str, str] = {}
    for macro, dotted_path in module.PAPER_NUMBER_JSON_FIELDS:
        macro_values[macro] = str(module._json_path_value(summary, dotted_path))
    for macro, dotted_path in module.PAPER_NUMBER_FLOAT_FIELDS:
        macro_values[macro] = module._format_paper_number_float(
            module._json_path_value(summary, dotted_path)
        )
    for macro, dotted_path in module.PAPER_NUMBER_SIX_DECIMAL_FIELDS:
        macro_values[macro] = module._format_paper_number_float(
            module._json_path_value(summary, dotted_path),
            precision=6,
        )
    macro_values.update(
        {
            "CVMLifecycleFullSurvived": "1",
            "CVMLifecycleFullTotal": "2",
            "CVMLifecycleStrictSurvived": "0",
            "CVMLifecycleStrictTotal": "1",
            "CVMFaultDetected": "1",
            "CVMFaultLocalized": "1",
            "CVMFaultTotal": "2",
        }
    )
    paper_numbers_path = root / "paper_numbers.tex"
    paper_numbers_path.write_text(
        "% generated by test\n"
        + "".join(
            f"\\newcommand{{\\{macro}}}{{{value}}}\n"
            for macro, value in sorted(macro_values.items())
        ),
        encoding="utf-8",
    )
    return summary_path, paper_numbers_path, lifecycle_path, fault_path


def _write_generated_table_fixture(root: Path, module) -> tuple[Path, Path, Path, Path]:
    summary_path, _paper_numbers_path, lifecycle_path, fault_path = _write_paper_number_fixture(
        root,
        module,
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    lifecycle_counts, lifecycle_failures = module._paper_number_lifecycle_counts(lifecycle_path)
    fault_counts, fault_failures = module._paper_number_fault_counts(fault_path)
    assert not lifecycle_failures
    assert not fault_failures
    tables = root / "tables"
    tables.mkdir()

    def write_table(name: str, rows: list[str]) -> None:
        header = module.EXPECTED_TABLE_HEADERS[name]
        (tables / name).write_text(
            "% generated by test; data_hash=abc\n"
            "\\begin{tabular}{lll}\n"
            "\\toprule\n"
            + f"{header} \\\\\n"
            + "\\midrule\n"
            + "\n".join(f"{row} \\\\" for row in rows)
            + "\n\\bottomrule\n\\end{tabular}\n",
            encoding="utf-8",
        )

    write_table("contract_map.tex", module._expected_contract_map_rows())
    write_table("main_results.tex", module._expected_main_results_rows(summary))
    write_table(
        "protocol_replay_policies.tex",
        module._expected_protocol_replay_policy_rows(summary),
    )
    write_table("ablations.tex", module._expected_ablations_rows(summary))
    write_table(
        "fault_localization.tex",
        module._expected_fault_localization_rows(lifecycle_counts, fault_counts),
    )
    return tables, summary_path, lifecycle_path, fault_path


def _write_summary_timestamp_fixture(root: Path) -> tuple[Path, Path]:
    results = root / "results"
    manifest_dir = root / "manifests" / "run_manifests"
    manifest_dir.mkdir(parents=True)
    matrix_dir = results / "core"
    matrix_dir.mkdir(parents=True)
    (matrix_dir / "runs.csv").write_text(
        "run_id,matrix\n"
        "core_constant_velocity_scene-a_17_full_contract,core\n"
        "core_route_following_scene-a_17_full_contract,core\n",
        encoding="utf-8",
    )
    (manifest_dir / "core_constant_velocity_scene-a_17_full_contract.json").write_text(
        json.dumps({"created_at": "2026-07-17T12:00:00+00:00"}),
        encoding="utf-8",
    )
    (manifest_dir / "core_route_following_scene-a_17_full_contract.json").write_text(
        json.dumps({"created_at": "2026-07-17T12:30:00+00:00"}),
        encoding="utf-8",
    )
    (matrix_dir / "summary.json").write_text(
        json.dumps({"matrix": "core", "created_at": "2026-07-17T12:30:00+00:00"}),
        encoding="utf-8",
    )
    (results / "summary.json").write_text(
        json.dumps({"created_at": "2026-07-17T12:30:00+00:00"}),
        encoding="utf-8",
    )
    return results, manifest_dir


class ValidateCVMSubmissionTests(unittest.TestCase):
    def test_reactive_artifact_integrity_matches_generated_summary(self) -> None:
        module = _load_module()

        failures = module._reactive_artifact_failures(
            repo_root=ROOT,
            summary_path=ROOT / "artifacts" / "cvm" / "results" / "summary.json",
        )

        self.assertEqual([], failures)

    def test_source_text_accepts_release_abstract_length(self) -> None:
        module = _load_module()
        body = " ".join(f"word{index}" for index in range(module.ABSTRACT_MIN_WORDS))
        source = (
            "\\documentclass[a4paper,10pt,conference]{ieeeconf}\n"
            "\\IEEEoverridecommandlockouts\n"
            "\\overrideIEEEmargins\n"
            "\\hypersetup{pdfsubject={AlpaBridge integration-failure attribution paper}}\n"
            "\\begin{abstract}\n" + body + " \\CVMTotalRows{}\n"
            "\\end{abstract}\n"
        )

        failures = module._source_text_failures(source_text=source, path=Path("main.tex"))

        self.assertEqual([], failures)

    def test_source_text_rejects_abstract_length_and_draft_metadata(self) -> None:
        module = _load_module()
        draft_subject = "paper " + "draft"
        source = (
            "\\documentclass[a4paper,10pt,conference]{ieeeconf}\n"
            "\\IEEEoverridecommandlockouts\n"
            "\\overrideIEEEmargins\n"
            f"\\hypersetup{{pdfsubject={{AlpaBridge contract-based system-integration {draft_subject}}}}}\n"
            "\\begin{abstract}\nshort abstract\n\\end{abstract}\n"
        )

        failures = module._source_text_failures(source_text=source, path=Path("main.tex"))

        self.assertIn("abstract_word_count_out_of_range:main.tex:2", failures)
        self.assertIn("source_pdfsubject_marked_draft:main.tex", failures)

    def test_source_text_ignores_commented_layout_commands(self) -> None:
        module = _load_module()
        body = " ".join(f"word{index}" for index in range(module.ABSTRACT_MIN_WORDS))
        source = (
            "\\documentclass[a4paper,10pt,conference]{ieeeconf}\n"
            "\\IEEEoverridecommandlockouts\n"
            "\\overrideIEEEmargins\n"
            "% \\usepackage{geometry}\n"
            "% \\vspace{-2em}\n"
            "\\begin{abstract}\n" + body + "\n\\end{abstract}\n"
        )

        failures = module._source_text_failures(source_text=source, path=Path("main.tex"))

        self.assertEqual([], failures)

    def test_source_text_rejects_layout_hacks_and_non_ieee_documentclass(self) -> None:
        module = _load_module()
        body = " ".join(f"word{index}" for index in range(module.ABSTRACT_MIN_WORDS))
        source = (
            "\\documentclass{article}\n"
            "\\usepackage{geometry}\n"
            "\\setlength{\\textwidth}{7in}\n"
            "\\pagestyle{plain}\n"
            "\\setcounter{page}{2}\n"
            "\\fontsize{9}{10}\\selectfont\n"
            "\\vspace{-1em}\n"
            "\\enlargethispage{1em}\n"
            "\\IEEEoverridecommandlockouts\n"
            "\\begin{abstract}\n" + body + "\n\\end{abstract}\n"
        )

        failures = module._source_text_failures(source_text=source, path=Path("main.tex"))

        self.assertIn("source_documentclass_not_ieeeconf_a4:main.tex", failures)
        self.assertIn("source_layout_hack:main.tex:geometry_package", failures)
        self.assertIn("source_layout_hack:main.tex:manual_margin_length", failures)
        self.assertIn("source_layout_hack:main.tex:manual_page_style", failures)
        self.assertIn("source_layout_hack:main.tex:manual_page_counter", failures)
        self.assertIn("source_layout_hack:main.tex:manual_font_scaling", failures)
        self.assertIn("source_layout_hack:main.tex:negative_spacing", failures)
        self.assertIn("source_layout_hack:main.tex:page_enlargement", failures)
        self.assertIn(
            "source_ieeeconf_command_missing:main.tex:overrideIEEEmargins",
            failures,
        )

    def test_latex_log_failures_report_reference_and_box_warnings(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.log"
            path.write_text(
                "LaTeX Warning: Citation `missing' undefined.\n"
                "Overfull \\hbox (1.0pt too wide) in paragraph.\n",
                encoding="utf-8",
            )

            failures = module._latex_log_failures(path)

        self.assertIn("latex_log_warning:Citation `", failures)
        self.assertIn("latex_log_warning:Overfull \\hbox", failures)

    def test_pdf_a4_page_size_accepts_portrait_a4_mediabox(self) -> None:
        module = _load_module()
        info = "Pages: 5\nMediaboxes (1):\n\t1\t(59 0 R):\t[ 0 0 595.276 841.89 ]\n"

        failures = module._pdf_a4_page_size_failures(info=info, path=Path("paper.pdf"))

        self.assertEqual([], failures)

    def test_pdf_a4_page_size_rejects_letter_or_missing_mediabox(self) -> None:
        module = _load_module()
        letter_info = "Pages: 1\nMediaboxes (1):\n\t1\t(59 0 R):\t[ 0 0 612 792 ]\n"

        letter_failures = module._pdf_a4_page_size_failures(
            info=letter_info,
            path=Path("paper.pdf"),
        )
        missing_failures = module._pdf_a4_page_size_failures(
            info="Pages: 1\n",
            path=Path("paper.pdf"),
        )

        self.assertEqual(["page_size_not_a4:paper.pdf:1:612.000x792.000"], letter_failures)
        self.assertEqual(["page_size_unavailable:paper.pdf"], missing_failures)

    def test_paper_metadata_text_accepts_matching_source(self) -> None:
        module = _load_module()
        abstract = " ".join(f"word{index}" for index in range(module.ABSTRACT_MIN_WORDS))
        source = (
            "\\title{Contract Title}\n"
            "\\IEEEauthorblockN{Researcher Name}\n"
            "Independent Researcher\n"
            "\\hypersetup{\n"
            "  pdftitle={Contract Title},\n"
            "  pdfauthor={Researcher Name},\n"
            "  pdfsubject={Contract metadata paper}\n"
            "}\n"
            "\\begin{abstract}\n" + abstract + "\n\\end{abstract}\n"
        )
        metadata = {
            "title": "Contract Title",
            "author": "Researcher Name",
            "affiliation": "Independent Researcher",
            "pdf_subject": "Contract metadata paper",
            "abstract_source_sha256": module._sha256_text(module._normalize_latex_source(abstract)),
            "abstract_word_count": module.ABSTRACT_MIN_WORDS,
        }

        failures = module._paper_metadata_text_failures(
            metadata=metadata,
            metadata_path=Path("metadata.json"),
            source_text=source,
            source_path=Path("main.tex"),
        )

        self.assertEqual([], failures)

    def test_paper_metadata_text_rejects_title_and_abstract_mismatch(self) -> None:
        module = _load_module()
        abstract = " ".join(f"word{index}" for index in range(module.ABSTRACT_MIN_WORDS))
        source = (
            "\\title{Contract Title}\n"
            "\\IEEEauthorblockN{Researcher Name}\n"
            "Independent Researcher\n"
            "\\hypersetup{pdftitle={Contract Title}, pdfauthor={Researcher Name}, "
            "pdfsubject={Contract metadata paper}}\n"
            "\\begin{abstract}\n" + abstract + "\n\\end{abstract}\n"
        )
        metadata = {
            "title": "Different Title",
            "author": "Researcher Name",
            "affiliation": "Independent Researcher",
            "pdf_subject": "Contract metadata paper",
            "abstract_source_sha256": "0" * 64,
            "abstract_word_count": module.ABSTRACT_MIN_WORDS + 1,
        }

        failures = module._paper_metadata_text_failures(
            metadata=metadata,
            metadata_path=Path("metadata.json"),
            source_text=source,
            source_path=Path("main.tex"),
        )

        self.assertIn("metadata_title_mismatch:main.tex:metadata.json", failures)
        self.assertIn("metadata_pdf_title_mismatch:main.tex:metadata.json", failures)
        self.assertIn("metadata_abstract_hash_mismatch:main.tex:metadata.json", failures)
        self.assertIn(
            "metadata_abstract_word_count_mismatch:main.tex:metadata.json:160:161",
            failures,
        )

    def test_pdf_metadata_text_accepts_utf16_hex_info_metadata(self) -> None:
        module = _load_module()

        def pdf_hex(value: str) -> str:
            return "<" + value.encode("utf-16").hex().upper() + ">"

        metadata = {
            "title": "Contract Title",
            "author": "Researcher Name",
            "pdf_subject": "Contract metadata paper",
        }
        paper_info = (
            "Info object (1 0 R):\n"
            f"<</Author{pdf_hex('Researcher Name')}"
            f"/Title{pdf_hex('Contract Title')}"
            f"/Subject{pdf_hex('Contract metadata paper')}>>\n"
        )

        failures = module._pdf_metadata_text_failures(
            metadata=metadata,
            metadata_path=Path("metadata.json"),
            paper_info=paper_info,
            paper_path=Path("paper.pdf"),
        )

        self.assertEqual([], failures)

    def test_pdf_metadata_text_rejects_output_metadata_mismatch(self) -> None:
        module = _load_module()
        metadata = {
            "title": "Contract Title",
            "author": "Researcher Name",
            "pdf_subject": "Contract metadata paper",
        }
        paper_info = (
            "Info object (1 0 R):\n<</Author(Researcher Name)/Title(Wrong Title)/Creator(LaTeX)>>\n"
        )

        failures = module._pdf_metadata_text_failures(
            metadata=metadata,
            metadata_path=Path("metadata.json"),
            paper_info=paper_info,
            paper_path=Path("paper.pdf"),
        )

        self.assertIn(
            "pdf_metadata_field_mismatch:paper.pdf:metadata.json:Title",
            failures,
        )
        self.assertIn("pdf_metadata_field_missing:paper.pdf:Subject", failures)

    def test_claim_boundary_text_requires_policy_integration_separation(self) -> None:
        module = _load_module()
        readme = (
            "## Failure Attribution Boundary\n"
            "integration failure and policy failure are separated before policy behavior. "
            "Rows are not policy failure until claim-valid. "
            "Integration/precondition/evidence failure is retained separately. "
            "This is not a framework-superiority test. These measurements are "
            "not end-to-end runtime or human time-to-diagnosis. No population confidence "
            "interval or hypothesis test is reported. AlpaBridge targets a policy interface, "
            "not WOMD scenes. The ablation does not measure how often this fault occurs. "
            "Waymax is a future binding target.\n"
        )
        source = (
            "\\subsection{Failure Attribution Rule}\n"
            "A row is classified as an integration, precondition, or evidence failure. "
            "Passing gates permits policy-behavior attribution, not automatic "
            "policy-failure attribution. "
            "\\CVMPolicyBehaviorAttributableRows{} "
            "\\CVMPolicyFailureAttributableRows{} "
            "\\CVMIntegrationFailureAttributableRows{}. These are not end-to-end runtime "
            "or human diagnosis time and not end-to-end runtime or time-to-diagnosis "
            "measurements. They "
            "are not evidence of population-level superiority to another integration "
            "framework. We do not compute a population confidence interval or "
            "hypothesis test.\n"
        )

        failures = module._claim_boundary_text_failures(
            readme_text=readme,
            readme_path=Path("README.md"),
            source_text=source,
            source_path=Path("main.tex"),
        )

        self.assertEqual([], failures)

    def test_claim_boundary_text_rejects_missing_policy_integration_terms(self) -> None:
        module = _load_module()

        failures = module._claim_boundary_text_failures(
            readme_text="AlpaBridge docs\n",
            readme_path=Path("README.md"),
            source_text="\\begin{abstract}AlpaBridge\\end{abstract}\n",
            source_path=Path("main.tex"),
        )

        self.assertIn(
            "claim_boundary_readme_missing:README.md:Failure Attribution Boundary",
            failures,
        )
        self.assertIn(
            "claim_boundary_source_missing:main.tex:Failure Attribution Rule",
            failures,
        )
        self.assertIn(
            "claim_boundary_source_missing:main.tex:\\CVMPolicyFailureAttributableRows{}",
            failures,
        )
        self.assertIn(
            "claim_boundary_readme_missing:README.md:not a framework-superiority test",
            failures,
        )
        self.assertIn(
            "claim_boundary_source_missing:main.tex:not end-to-end runtime or human diagnosis time",
            failures,
        )

    def test_summary_timestamp_validation_accepts_manifest_derived_timestamps(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            results, manifest_dir = _write_summary_timestamp_fixture(Path(tmp))

            failures = module._summary_timestamp_failures(
                results_dir=results,
                manifest_dir=manifest_dir,
            )

        self.assertEqual([], failures)

    def test_summary_timestamp_validation_rejects_wall_clock_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            results, manifest_dir = _write_summary_timestamp_fixture(Path(tmp))
            (results / "core" / "summary.json").write_text(
                json.dumps({"matrix": "core", "created_at": "2026-07-17T13:00:00+00:00"}),
                encoding="utf-8",
            )
            (results / "summary.json").write_text(
                json.dumps({"created_at": "2026-07-17T13:15:00+00:00"}),
                encoding="utf-8",
            )

            failures = module._summary_timestamp_failures(
                results_dir=results,
                manifest_dir=manifest_dir,
            )

        self.assertIn(
            "matrix_summary_created_at_mismatch:"
            f"{results / 'core' / 'summary.json'}:"
            "2026-07-17T13:00:00+00:00:2026-07-17T12:30:00+00:00",
            failures,
        )
        self.assertIn(
            "aggregate_summary_created_at_mismatch:"
            f"{results / 'summary.json'}:"
            "2026-07-17T13:15:00+00:00:2026-07-17T13:00:00+00:00",
            failures,
        )

    def test_readme_visual_explanation_accepts_executed_replay_terms(self) -> None:
        module = _load_module()
        readme = (
            "## Executed Ablation: Route Geometry vs. Command Only\n"
            "The same official AlpaSim integration log runs through four live "
            "AlpaBridge gRPC services under route-retaining and command-only service "
            "modes. The route arm reports semantic.command_only; the learned "
            "command-only arm correctly passes and paired outputs remain exactly "
            "equal. The recorded camera and ego-state sequence is fixed. The replay "
            "is non-reactive and is not a reactive simulator rollout, policy-quality "
            "comparison, or cross-simulator test. This deliberate format ablation is "
            "not missing AlpaSim data: the same 20 `(x,y)` route waypoints enter both "
            "arms. It retains the high-level `LEFT` command but hides coordinates "
            "from the same route-following policy. Both plots use the same axes in "
            "meters and report a 1.506 m separation. The camera and ego-state "
            "messages are fixed and do not show a reactive future. This is not a "
            "competing policy or integration framework. "
            "See alpasim-protocol-replay.mp4, the validated manifest, and "
            "reproduction notes.\n"
        )

        failures = module._readme_visual_explanation_failures(
            readme_text=readme,
            readme_path=Path("README.md"),
        )

        self.assertEqual([], failures)

    def test_readme_visual_explanation_rejects_unproven_replay_context(self) -> None:
        module = _load_module()

        failures = module._readme_visual_explanation_failures(
            readme_text="## Executed Ablation: Route Geometry vs. Command Only\nNice camera output.\n",
            readme_path=Path("README.md"),
        )

        self.assertIn(
            "readme_visual_explanation_missing:README.md:four live AlpaBridge gRPC services",
            failures,
        )
        self.assertIn(
            "readme_visual_explanation_missing:README.md:non-reactive",
            failures,
        )
        self.assertIn(
            "readme_visual_explanation_missing:README.md:deliberate format ablation",
            failures,
        )

    def test_evaluation_status_accepts_diagnostic_and_benchmark_boundary(self) -> None:
        module = _load_module()
        evaluation = (
            "The CVM includes completed dependency-light closed-loop diagnostic rows "
            "on locally available gated scene assets, completed semantic "
            "route-boundary ablations. The completed full-contract and "
            "semantic-ablation rollouts are integration-effectiveness evidence. "
            "Synthetic lifecycle/fault rows are service-harness conformance "
            "diagnostics only. Controlled trace mutations measure post-parse "
            "detector execution latency and a paired guard-path increment. Blocked rows are retained as denominator/context "
            "rather than success metrics. The public release core is the "
            "dependency-light adapter path. Direct-actor, learned-checkpoint, and "
            "restricted-scene dependencies are optional gated extensions, not "
            "release-core dependencies. The release does not redistribute a "
            "checkpoint or scene subset and excludes verified scene-category "
            "coverage and a claim-ready closed-loop policy benchmark.\n"
        )

        failures = module._evaluation_status_failures(
            evaluation_text=evaluation,
            evaluation_path=Path("docs/evaluation.md"),
        )

        self.assertEqual([], failures)

    def test_evaluation_status_rejects_ambiguous_current_status(self) -> None:
        module = _load_module()

        failures = module._evaluation_status_failures(
            evaluation_text="The release has no benchmark result.\n",
            evaluation_path=Path("docs/evaluation.md"),
        )

        self.assertIn(
            "evaluation_status_missing:docs/evaluation.md:completed dependency-light closed-loop diagnostic rows",
            failures,
        )
        self.assertIn(
            "evaluation_status_missing:docs/evaluation.md:service-harness conformance diagnostics only",
            failures,
        )

    def test_summary_attribution_requires_policy_partition(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(
                json.dumps(
                    {
                        "total_rows": 3,
                        "failure_attribution": {
                            "rule": (
                                "policy failure after semantic temporal lifecycle "
                                "deployment evidence gates"
                            ),
                            "contract_valid_closed_loop_rows": 1,
                            "integration_or_evidence_invalid_closed_loop_rows": 1,
                            "precondition_blocked_rows": 1,
                            "claim_valid_policy_benchmark_rows": 1,
                            "policy_behavior_attributable_rows": 1,
                            "policy_failure_attributable_rows": 0,
                            "integration_failure_attributable_rows": 1,
                            "diagnostic_not_policy_rows": 1,
                            "non_policy_attributed_rows": 2,
                        },
                    }
                ),
                encoding="utf-8",
            )

            failures = module._summary_attribution_failures(path)

        self.assertEqual([], failures)

    def test_summary_attribution_rejects_policy_failure_without_behavior(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(
                json.dumps(
                    {
                        "total_rows": 3,
                        "failure_attribution": {
                            "rule": "policy failure",
                            "claim_valid_policy_benchmark_rows": 0,
                            "policy_behavior_attributable_rows": 0,
                            "policy_failure_attributable_rows": 1,
                            "non_policy_attributed_rows": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )

            failures = module._summary_attribution_failures(path)

        self.assertIn(f"summary_policy_failure_exceeds_behavior:{path}", failures)
        self.assertIn(f"summary_policy_attribution_partition_mismatch:{path}", failures)
        self.assertIn(
            f"summary_attribution_field_missing:{path}:integration_failure_attributable_rows",
            failures,
        )

    def test_summary_scenario_coverage_rejects_claim_with_unclassified_scenes(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(
                json.dumps(
                    {
                        "scenario_coverage": {
                            "rule": (
                                "authoritative metadata is required because unclassified "
                                "scenes are integration instances, not coverage evidence"
                            ),
                            "closed_loop_scene_count": 6,
                            "required_category_count": 6,
                            "verified_required_category_count": 5,
                            "unclassified_closed_loop_scene_count": 1,
                            "scenario_category_coverage_claimed": True,
                            "scenario_category_coverage_claimed_int": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            failures = module._summary_scenario_coverage_failures(path)

        self.assertIn(
            f"summary_scenario_coverage_claim_without_required_categories:{path}",
            failures,
        )
        self.assertIn(
            f"summary_scenario_coverage_claim_with_unclassified_scenes:{path}",
            failures,
        )

    def test_readme_summary_count_check_accepts_synced_counts(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path, _paper_numbers_path, _lifecycle_path, _fault_path = (
                _write_paper_number_fixture(root, module)
            )
            readme = (
                "The generated aggregate makes the boundary numeric: current artifacts contain "
                "`3` policy-attributable behavior rows, `0` policy-attributable failure rows, "
                "`2` integration/precondition blocker rows, and `4` completed non-policy diagnostic rows "
                "that remain non-policy-attributed.\n"
            )

            failures = module._readme_summary_count_failures(
                readme_text=readme,
                readme_path=Path("README.md"),
                summary_path=summary_path,
            )

        self.assertEqual([], failures)

    def test_readme_summary_count_check_rejects_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path, _paper_numbers_path, _lifecycle_path, _fault_path = (
                _write_paper_number_fixture(root, module)
            )
            readme = (
                "`999` policy-attributable behavior rows, "
                "`0` policy-attributable failure rows, "
                "`2` integration/precondition blocker rows, and "
                "`4` completed non-policy diagnostic rows.\n"
            )

            failures = module._readme_summary_count_failures(
                readme_text=readme,
                readme_path=Path("README.md"),
                summary_path=summary_path,
            )

        self.assertIn(
            "readme_summary_count_mismatch:README.md:"
            "policy_behavior_attributable_rows:`3` policy-attributable behavior rows",
            failures,
        )

    def test_paper_number_macro_check_accepts_summary_and_csv_synced_macros(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path, paper_numbers_path, lifecycle_path, fault_path = (
                _write_paper_number_fixture(root, module)
            )

            failures = module._paper_number_macro_failures(
                summary_path=summary_path,
                paper_numbers_path=paper_numbers_path,
                lifecycle_path=lifecycle_path,
                fault_path=fault_path,
            )

        self.assertEqual([], failures)

    def test_paper_number_macro_check_rejects_summary_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path, paper_numbers_path, lifecycle_path, fault_path = (
                _write_paper_number_fixture(root, module)
            )
            paper_numbers_path.write_text(
                paper_numbers_path.read_text(encoding="utf-8").replace(
                    "\\newcommand{\\CVMTotalRows}{10}",
                    "\\newcommand{\\CVMTotalRows}{999}",
                ),
                encoding="utf-8",
            )

            failures = module._paper_number_macro_failures(
                summary_path=summary_path,
                paper_numbers_path=paper_numbers_path,
                lifecycle_path=lifecycle_path,
                fault_path=fault_path,
            )

        self.assertIn(
            f"paper_numbers_macro_mismatch:{paper_numbers_path}:CVMTotalRows:999:10",
            failures,
        )

    def test_generated_table_value_check_accepts_summary_synced_tables(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables, summary_path, lifecycle_path, fault_path = _write_generated_table_fixture(
                root,
                module,
            )

            failures = module._generated_table_value_failures(
                tables=tables,
                summary_path=summary_path,
                lifecycle_path=lifecycle_path,
                fault_path=fault_path,
            )

        self.assertEqual([], failures)

    def test_generated_table_value_check_rejects_table_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables, summary_path, lifecycle_path, fault_path = _write_generated_table_fixture(
                root,
                module,
            )
            main_results = tables / "main_results.tex"
            main_results.write_text(
                main_results.read_text(encoding="utf-8").replace(
                    r"constant\_velocity & 4 & 3/3 & 3/3 & 3/3 & 3/3 & 0 & 1",
                    r"constant\_velocity & 4 & 3/3 & 3/3 & 3/3 & 3/3 & 0 & 999",
                ),
                encoding="utf-8",
            )

            failures = module._generated_table_value_failures(
                tables=tables,
                summary_path=summary_path,
                lifecycle_path=lifecycle_path,
                fault_path=fault_path,
            )

        self.assertIn(
            f"generated_table_row_mismatch:{main_results}:"
            r"constant\_velocity & 4 & 3/3 & 3/3 & 3/3 & 3/3 & 0 & 1",
            failures,
        )

    def test_generated_table_value_check_rejects_header_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables, summary_path, lifecycle_path, fault_path = _write_generated_table_fixture(
                root,
                module,
            )
            main_results = tables / "main_results.tex"
            main_results.write_text(
                main_results.read_text(encoding="utf-8").replace(
                    "Route & Sensor",
                    "Route status & Sensor status",
                ),
                encoding="utf-8",
            )

            failures = module._generated_table_value_failures(
                tables=tables,
                summary_path=summary_path,
                lifecycle_path=lifecycle_path,
                fault_path=fault_path,
            )

        self.assertIn(
            f"generated_table_header_mismatch:{main_results}:"
            "Public core policy & Rows & Done/att. & Audit & Route & Sensor & Crash & Blocked",
            failures,
        )

    def test_generated_table_value_check_rejects_missing_summary_field(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables, summary_path, lifecycle_path, fault_path = _write_generated_table_fixture(
                root,
                module,
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            del summary["integration_effectiveness"]["full_contract_completed_runs"]
            summary_path.write_text(json.dumps(summary), encoding="utf-8")

            failures = module._generated_table_value_failures(
                tables=tables,
                summary_path=summary_path,
                lifecycle_path=lifecycle_path,
                fault_path=fault_path,
            )

        self.assertIn(
            "generated_table_summary_field_missing:"
            f"{summary_path}:integration_effectiveness.full_contract_completed_runs",
            failures,
        )

    def test_diagnostic_timing_claims_must_match_summary(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "diagnostic_experiment": {
                            "timing": {
                                "fault_case_detector_us": {
                                    "p50": 1.111,
                                    "p95": 2.222,
                                }
                            },
                            "adapter_guard_path_timing": {
                                "paired_incremental_us": {
                                    "p50": 3.333,
                                    "p95": 4.444,
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            claim_text = "1.111 us 2.222 us 3.333 us 4.444 us\n"
            for relative_path in module.DIAGNOSTIC_TIMING_CLAIM_PATHS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(claim_text, encoding="utf-8")

            self.assertEqual(
                [],
                module._diagnostic_timing_claim_failures(
                    repo_root=root,
                    summary_path=summary_path,
                ),
            )

            stale_path = root / module.DIAGNOSTIC_TIMING_CLAIM_PATHS[0]
            stale_path.write_text("1.111 us 2.222 us 3.333 us\n", encoding="utf-8")
            failures = module._diagnostic_timing_claim_failures(
                repo_root=root,
                summary_path=summary_path,
            )

        self.assertIn(
            f"diagnostic_timing_claim_mismatch:{stale_path}:guard_increment_p95:4.444",
            failures,
        )

    def test_claim_evidence_matrix_accepts_summary_synced_counts(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "summary.json"
            matrix_path = root / "claim_evidence_matrix.md"
            summary = {
                "total_rows": 145,
                "attempted_runs": 109,
                "completed_runs": 109,
                "closed_loop_completed_runs": 54,
                "planned_runs": 0,
                "blocked_runs": 36,
                "integration_effectiveness": {
                    "full_contract_audit_valid_runs": 45,
                    "full_contract_completed_runs": 45,
                    "semantic_ablation_comparison_eligible_pairs": 9,
                    "semantic_ablation_completed_pairs": 9,
                    "semantic_ablation_command_proxy_rejected_runs": 9,
                    "semantic_ablation_command_proxy_completed_runs": 9,
                    "status_only_baseline_accepted_runs": 9,
                    "status_only_baseline_acceptance_denominator": 9,
                    "contract_invalid_evidence_rejected_runs": 9,
                    "contract_invalid_evidence_rejection_denominator": 9,
                },
                "scenario_coverage": {
                    "closed_loop_scene_count": 6,
                    "required_category_count": 6,
                    "verified_required_category_count": 0,
                    "unclassified_closed_loop_scene_count": 6,
                    "scenario_category_coverage_claimed": False,
                    "scenario_category_coverage_claimed_int": 0,
                },
                "failure_attribution": {
                    "contract_valid_closed_loop_rows": 45,
                    "integration_or_evidence_invalid_closed_loop_rows": 9,
                    "policy_behavior_attributable_rows": 45,
                    "policy_failure_attributable_rows": 0,
                    "non_policy_attributed_rows": 100,
                    "claim_valid_policy_benchmark_rows": 0,
                },
                "release_scope": {
                    "public_core_completed_runs": 36,
                    "public_core_configured_rows": 36,
                },
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            matrix_path.write_text(
                "\n".join(
                    [
                        "# Claim Evidence Matrix",
                        "",
                        "## Aggregate Status",
                        "",
                        "- Configured rows: 145.",
                        "- Public-core rows completed: 36/36.",
                        "- Attempted rows: 109.",
                        "- Completed rows: 109.",
                        "- Closed-loop completed rows: 54.",
                        "- Full-contract rows audit-valid: 45/45.",
                        "- Comparison-eligible semantic pairs: 9/9.",
                        "- Command-only rows rejected as non-claim-valid: 9/9.",
                        "- Status-only baseline accepted rows: 9/9.",
                        "- Contract-invalid route evidence rejected: 9/9.",
                        "- Closed-loop unique scenes: 6.",
                        "- Verified required scenario categories: 0/6.",
                        "- Unclassified closed-loop scenes: 6.",
                        "- Contract-valid closed-loop rows: 45.",
                        "- Integration/evidence-invalid closed-loop rows: 9.",
                        "- Policy-attributable behavior rows: 45.",
                        "- Policy-attributable failure rows: 0.",
                        "- Non-policy-attributed rows: 100.",
                        "- Claim-valid policy benchmark rows: 0.",
                        "- Planned rows: 0.",
                        "- Blocked rows: 36.",
                        "- Aggregate artifact: `artifacts/cvm/results/summary.json`.",
                    ]
                ),
                encoding="utf-8",
            )

            failures = module._claim_evidence_matrix_failures(
                matrix_path=matrix_path,
                summary_path=summary_path,
            )

        self.assertEqual([], failures)

    def test_claim_evidence_matrix_rejects_summary_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "summary.json"
            matrix_path = root / "claim_evidence_matrix.md"
            summary = {
                "total_rows": 2,
                "attempted_runs": 2,
                "completed_runs": 2,
                "closed_loop_completed_runs": 1,
                "planned_runs": 0,
                "blocked_runs": 0,
                "integration_effectiveness": {
                    "full_contract_audit_valid_runs": 1,
                    "full_contract_completed_runs": 1,
                    "semantic_ablation_comparison_eligible_pairs": 0,
                    "semantic_ablation_completed_pairs": 0,
                    "semantic_ablation_command_proxy_rejected_runs": 0,
                    "semantic_ablation_command_proxy_completed_runs": 0,
                    "status_only_baseline_accepted_runs": 0,
                    "status_only_baseline_acceptance_denominator": 0,
                    "contract_invalid_evidence_rejected_runs": 0,
                    "contract_invalid_evidence_rejection_denominator": 0,
                },
                "scenario_coverage": {
                    "closed_loop_scene_count": 1,
                    "required_category_count": 6,
                    "verified_required_category_count": 0,
                    "unclassified_closed_loop_scene_count": 1,
                    "scenario_category_coverage_claimed": False,
                    "scenario_category_coverage_claimed_int": 0,
                },
                "failure_attribution": {
                    "contract_valid_closed_loop_rows": 1,
                    "integration_or_evidence_invalid_closed_loop_rows": 0,
                    "policy_behavior_attributable_rows": 1,
                    "policy_failure_attributable_rows": 0,
                    "non_policy_attributed_rows": 1,
                    "claim_valid_policy_benchmark_rows": 0,
                },
                "release_scope": {
                    "public_core_completed_runs": 1,
                    "public_core_configured_rows": 1,
                },
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            matrix_path.write_text(
                "- Configured rows: 3.\n"
                "- Aggregate artifact: `artifacts/cvm/results/summary.json`.\n",
                encoding="utf-8",
            )

            failures = module._claim_evidence_matrix_failures(
                matrix_path=matrix_path,
                summary_path=summary_path,
            )

        self.assertIn(
            f"claim_evidence_matrix_count_mismatch:{matrix_path}:Configured rows:2",
            failures,
        )
        self.assertIn(
            f"claim_evidence_matrix_count_mismatch:{matrix_path}:Completed rows:2",
            failures,
        )

    def test_contract_test_audit_accepts_required_traceability(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_alpasim_integration.py").write_text("", encoding="utf-8")
            audit_path = root / "contract_test_audit.md"
            audit_path.write_text(
                "\n".join(
                    [
                        "# Contract Test Audit",
                        "Covered; Partially covered; Gap; policy claims.",
                        "## Semantic Contract",
                        "`tests/test_alpasim_integration.py`",
                        "## Temporal Contract",
                        "## Lifecycle Contract",
                        "## Deployment And Plugin-Dependency Contract",
                        "## Evidence Contract",
                        "## Fault-Injection Diagnostics",
                        "## Explicit Gaps Kept Out Of Policy Claims",
                    ]
                ),
                encoding="utf-8",
            )

            failures = module._contract_test_audit_failures(
                audit_path=audit_path,
                tests_dir=tests_dir,
            )

        self.assertEqual([], failures)

    def test_contract_test_audit_rejects_missing_terms_and_test_files(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            audit_path = root / "contract_test_audit.md"
            audit_path.write_text(
                "# Contract Test Audit\n## Semantic Contract\n`tests/test_missing.py`\n",
                encoding="utf-8",
            )

            failures = module._contract_test_audit_failures(
                audit_path=audit_path,
                tests_dir=tests_dir,
            )

        self.assertIn(
            f"contract_test_audit_missing:{audit_path}:Temporal Contract",
            failures,
        )
        self.assertIn(
            f"contract_test_audit_missing:{audit_path}:Explicit Gaps Kept Out Of Policy Claims",
            failures,
        )
        self.assertIn(
            f"contract_test_audit_missing_test_file:{audit_path}:tests/test_missing.py",
            failures,
        )

    def test_generated_artifact_hash_check_accepts_matching_tables_and_figures(self) -> None:
        module = _load_module()
        data_hash = "abc123"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables = root / "tables"
            figures = root / "figures"
            tables.mkdir()
            figures.mkdir()
            for name in module.REQUIRED_TABLES:
                (tables / name).write_text(
                    f"% generated by test; data_hash={data_hash}\n",
                    encoding="utf-8",
                )
            for name in module.REQUIRED_FIGURES:
                (figures / name).write_bytes(b"%PDF-1.5\n")

            with patch.object(
                module, "_mutool_info", return_value=f"Subject(data_hash={data_hash})"
            ):
                failures = module._generated_artifact_failures(
                    data_hash=data_hash,
                    table_dirs=(tables,),
                    figure_dirs=(figures,),
                )

        self.assertEqual([], failures)

    def test_generated_artifact_hash_check_reports_mismatches(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables = root / "tables"
            figures = root / "figures"
            tables.mkdir()
            figures.mkdir()
            for name in module.REQUIRED_TABLES:
                (tables / name).write_text("% generated by test; data_hash=old\n", encoding="utf-8")
            for name in module.REQUIRED_FIGURES:
                (figures / name).write_bytes(b"%PDF-1.5\n")

            with patch.object(module, "_mutool_info", return_value="Subject(data_hash=old)"):
                failures = module._generated_artifact_failures(
                    data_hash="new",
                    table_dirs=(tables,),
                    figure_dirs=(figures,),
                )

        self.assertIn(
            f"generated_table_hash_mismatch:{tables / module.REQUIRED_TABLES[0]}", failures
        )
        self.assertIn(
            f"generated_figure_hash_mismatch:{figures / module.REQUIRED_FIGURES[0]}",
            failures,
        )

    def test_paper_generated_copy_check_accepts_matching_copies(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_tables = root / "canonical_tables"
            paper_tables = root / "paper_tables"
            canonical_figures = root / "canonical_figures"
            paper_figures = root / "paper_figures"
            for directory in (canonical_tables, paper_tables, canonical_figures, paper_figures):
                directory.mkdir()
            for name in module.REQUIRED_TABLES:
                (canonical_tables / name).write_text("% data_hash=abc\n", encoding="utf-8")
                (paper_tables / name).write_text("% data_hash=abc\n", encoding="utf-8")
            for name in module.REQUIRED_FIGURES:
                (canonical_figures / name).write_bytes(b"%PDF-1.5\nsame")
                (paper_figures / name).write_bytes(b"%PDF-1.5\nsame")

            failures = module._paper_generated_copy_failures(
                canonical_tables=canonical_tables,
                paper_tables=paper_tables,
                canonical_figures=canonical_figures,
                paper_figures=paper_figures,
            )

        self.assertEqual([], failures)

    def test_paper_generated_copy_check_reports_drift(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_tables = root / "canonical_tables"
            paper_tables = root / "paper_tables"
            canonical_figures = root / "canonical_figures"
            paper_figures = root / "paper_figures"
            for directory in (canonical_tables, paper_tables, canonical_figures, paper_figures):
                directory.mkdir()
            for name in module.REQUIRED_TABLES:
                (canonical_tables / name).write_text("% data_hash=abc\n", encoding="utf-8")
                (paper_tables / name).write_text("% data_hash=abc\n", encoding="utf-8")
            for name in module.REQUIRED_FIGURES:
                (canonical_figures / name).write_bytes(b"%PDF-1.5\nsame")
                (paper_figures / name).write_bytes(b"%PDF-1.5\nsame")
            (paper_tables / module.REQUIRED_TABLES[0]).write_text(
                "% data_hash=abc\nmanual edit\n",
                encoding="utf-8",
            )
            (paper_figures / module.REQUIRED_FIGURES[0]).write_bytes(b"%PDF-1.5\nmanual")

            failures = module._paper_generated_copy_failures(
                canonical_tables=canonical_tables,
                paper_tables=paper_tables,
                canonical_figures=canonical_figures,
                paper_figures=paper_figures,
            )

        self.assertIn(
            f"paper_generated_table_drift:{paper_tables / module.REQUIRED_TABLES[0]}:"
            f"{canonical_tables / module.REQUIRED_TABLES[0]}",
            failures,
        )
        self.assertIn(
            f"paper_generated_figure_drift:{paper_figures / module.REQUIRED_FIGURES[0]}:"
            f"{canonical_figures / module.REQUIRED_FIGURES[0]}",
            failures,
        )

    def test_pdf_font_embedding_accepts_embedded_font_descriptor(self) -> None:
        module = _load_module()
        path = Path("paper.pdf")
        font_info = "Fonts (1):\n\t1\t(1 0 R):\tType1 'ABCDEF+Nimbus' (10 0 R)\n"

        def show(_path: Path, object_id: str) -> str:
            return {
                "10": "<< /Type /Font /FontDescriptor 11 0 R >>",
                "11": "<< /Type /FontDescriptor /FontFile 12 0 R >>",
            }[object_id]

        with (
            patch.object(module, "_mutool_info_fonts", return_value=font_info),
            patch.object(module, "_mutool_show", side_effect=show),
        ):
            failures = module._pdf_font_embedding_failures(path)

        self.assertEqual([], failures)

    def test_pdf_font_embedding_accepts_descendant_font_descriptor(self) -> None:
        module = _load_module()
        path = Path("paper.pdf")
        font_info = "Fonts (1):\n\t1\t(1 0 R):\tType0 'ABCDEF+CIDFont' (10 0 R)\n"

        def show(_path: Path, object_id: str) -> str:
            return {
                "10": "<< /Type /Font /DescendantFonts [ 20 0 R ] >>",
                "20": "<< /Type /Font /FontDescriptor 21 0 R >>",
                "21": "<< /Type /FontDescriptor /FontFile2 22 0 R >>",
            }[object_id]

        with (
            patch.object(module, "_mutool_info_fonts", return_value=font_info),
            patch.object(module, "_mutool_show", side_effect=show),
        ):
            failures = module._pdf_font_embedding_failures(path)

        self.assertEqual([], failures)

    def test_pdf_font_embedding_rejects_unembedded_font_descriptor(self) -> None:
        module = _load_module()
        path = Path("paper.pdf")
        font_info = "Fonts (1):\n\t1\t(1 0 R):\tType1 'ABCDEF+Nimbus' (10 0 R)\n"

        def show(_path: Path, object_id: str) -> str:
            return {
                "10": "<< /Type /Font /FontDescriptor 11 0 R >>",
                "11": "<< /Type /FontDescriptor /FontName /ABCDEF+Nimbus >>",
            }[object_id]

        with (
            patch.object(module, "_mutool_info_fonts", return_value=font_info),
            patch.object(module, "_mutool_show", side_effect=show),
        ):
            failures = module._pdf_font_embedding_failures(path)

        self.assertEqual(["font_not_embedded:paper.pdf:ABCDEF+Nimbus:11"], failures)

    def test_release_hygiene_accepts_clean_public_surface(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "AlpaBridge release notes [paper](alpabridge.pdf) "
                "[docs](docs/README.md#start) "
                "![rollout panel](docs/assets/readme/panel.svg) "
                '<img src="docs/assets/readme/panel.svg" alt="panel"> '
                "[external](https://example.com)\n",
                encoding="utf-8",
            )
            (root / "alpabridge.pdf").write_bytes(b"%PDF-1.5\n")
            (root / "docs" / "assets" / "readme").mkdir(parents=True)
            (root / "docs" / "README.md").write_text("Docs\n", encoding="utf-8")
            (root / "docs" / "assets" / "readme" / "panel.svg").write_text(
                "<svg></svg>\n",
                encoding="utf-8",
            )
            (root / "paper" / "cvm").mkdir(parents=True)
            (root / "paper" / "cvm" / "main.tex").write_text(
                "Contract-based integration paper\n",
                encoding="utf-8",
            )
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(_valid_ci_workflow_fixture(), encoding="utf-8")
            for relative_path, terms in module.COMMUNITY_DOC_REQUIREMENTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(terms), encoding="utf-8")

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertEqual([], failures)

    def test_release_hygiene_reports_public_images_without_alt_text(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "assets").mkdir(parents=True)
            (root / "docs" / "assets" / "panel.svg").write_text("<svg></svg>\n", encoding="utf-8")
            (root / "README.md").write_text(
                "![](docs/assets/panel.svg)\n"
                '<img src="docs/assets/panel.svg">\n'
                '<img src="https://example.com/remote.svg" alt="">\n',
                encoding="utf-8",
            )
            (root / "alpabridge.pdf").write_bytes(b"%PDF-1.5\n")

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn("public_image_alt_missing:README.md:docs/assets/panel.svg", failures)
        self.assertIn("public_image_alt_missing:README.md:https://example.com/remote.svg", failures)

    def test_release_hygiene_reports_missing_or_escaping_public_local_references(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "[missing](docs/missing.md)\n"
                "![missing image](docs/assets/missing.svg)\n"
                "[escape](../outside.md)\n",
                encoding="utf-8",
            )
            (root / "alpabridge.pdf").write_bytes(b"%PDF-1.5\n")

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn("public_local_reference_missing:README.md:docs/missing.md", failures)
        self.assertIn("public_local_reference_missing:README.md:docs/assets/missing.svg", failures)
        self.assertIn("public_local_reference_outside_root:README.md:../outside.md", failures)

    def test_repository_inventory_accepts_current_test_file_count(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpabridge.pdf").write_bytes(b"pdf")
            (root / "tests").mkdir()
            (root / "tests" / "test_alpha.py").write_text("", encoding="utf-8")
            (root / "tests" / "test_beta.py").write_text("", encoding="utf-8")
            report_dir = root / "artifacts" / "cvm" / "reports"
            report_dir.mkdir(parents=True)
            (report_dir / "repository_inventory.md").write_text(
                "- PDF size at audit: 3 bytes.\n"
                "- Test directory: `tests` with 2 top-level test files. Runtime pass/skip "
                "counts are recorded in [`test_report.md`](test_report.md).\n",
                encoding="utf-8",
            )

            failures = module._repository_inventory_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_repository_inventory_reports_stale_test_count(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpabridge.pdf").write_bytes(b"pdf")
            (root / "tests").mkdir()
            (root / "tests" / "test_alpha.py").write_text("", encoding="utf-8")
            report_dir = root / "artifacts" / "cvm" / "reports"
            report_dir.mkdir(parents=True)
            (report_dir / "repository_inventory.md").write_text(
                "- PDF size at audit: 999 bytes.\n"
                "- Test directory: `tests` with 3 top-level test files and 300 passing "
                "dependency-light conformance tests in the latest release gate.\n",
                encoding="utf-8",
            )

            failures = module._repository_inventory_failures(repo_root=root)

        self.assertIn(
            "repository_inventory_test_count_mismatch:"
            "artifacts/cvm/reports/repository_inventory.md:1:3",
            failures,
        )
        self.assertIn(
            "repository_inventory_missing_test_report_reference:artifacts/cvm/reports/repository_inventory.md",
            failures,
        )
        self.assertIn(
            "repository_inventory_stale_pass_count:artifacts/cvm/reports/repository_inventory.md",
            failures,
        )
        self.assertIn(
            "repository_inventory_pdf_size_mismatch:"
            "artifacts/cvm/reports/repository_inventory.md:3:999",
            failures,
        )

    def test_baseline_report_accepts_current_release_gate_evidence(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "artifacts" / "cvm" / "reports"
            report_dir.mkdir(parents=True)
            (report_dir / "baseline_report.md").write_text(
                "# Baseline And Final Audit Report\n\n"
                "## Current Release Gate Evidence\n\n"
                "| Command | Result |\n"
                "|---|---|\n"
                "| `uv run python -m pytest -q tests/test_validate_cvm_submission.py` | Passed. |\n"
                "| `make paper-verify PYTHON='uv run python'` | Passed. |\n"
                "| `make cvm-check PYTHON='uv run python'` | Passed with "
                "392 passed, 14 skipped, and 15 subtests passed. |\n"
                "| `make verify` | Passed with 65.43% against the configured 33.0% minimum. |\n",
                encoding="utf-8",
            )

            failures = module._baseline_report_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_baseline_report_rejects_historical_or_stale_gate_evidence(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "artifacts" / "cvm" / "reports"
            report_dir.mkdir(parents=True)
            (report_dir / "baseline_report.md").write_text(
                "# Baseline And Final Audit Report\n\n"
                "## Historical Baseline And Quality Gates\n\n"
                "| `./.venv/bin/python -m pytest -q` | "
                "247 passed after release-validator hardening. |\n",
                encoding="utf-8",
            )

            failures = module._baseline_report_failures(repo_root=root)

        self.assertIn(
            "baseline_report_forbidden:artifacts/cvm/reports/baseline_report.md:historical_release_gate",
            failures,
        )
        self.assertIn(
            "baseline_report_forbidden:artifacts/cvm/reports/baseline_report.md:venv_python_gate",
            failures,
        )
        self.assertIn(
            "baseline_report_forbidden:artifacts/cvm/reports/baseline_report.md:stale_hardening_count",
            failures,
        )
        self.assertIn(
            "baseline_report_missing_term:artifacts/cvm/reports/baseline_report.md:"
            "Current Release Gate Evidence",
            failures,
        )

    def test_release_hygiene_accepts_defined_cvm_acronym(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme = root / "README.md"
            readme.write_text(
                "The contract-validation matrix (CVM) keeps configured rows separate.\n",
                encoding="utf-8",
            )

            failures = module._cvm_acronym_definition_failures(
                path=readme,
                text=readme.read_text(encoding="utf-8"),
                root=root,
            )

        self.assertEqual([], failures)

    def test_release_hygiene_reports_undefined_cvm_acronym(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme = root / "README.md"
            readme.write_text("The CVM has configured rows.\n", encoding="utf-8")

            failures = module._cvm_acronym_definition_failures(
                path=readme,
                text=readme.read_text(encoding="utf-8"),
                root=root,
            )

        self.assertEqual(["public_hygiene:cvm_acronym_undefined:README.md"], failures)

    def test_release_hygiene_reports_sensitive_or_weak_public_text(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = "hf_" + ("A" * 20)
            fixture = "spot" + "light_reflex"
            unsupported_claim = "we " + "outperform baselines"
            draft_label = "paper " + "draft"
            generated_draft_url = "auto-" + "draft-214"
            venue_style_benchmark_label = "Neur" + "IPS-" + "style benchmark"
            weak_adapter_label = "adapter and evaluation " + "artifact"
            scaffold_label = "artifact " + "scaffold"
            venue_label = "venue-" + "specific row names"
            stale_event_name = "s" + "ii2027"
            third_party_secret = "hf_" + ("B" * 20)
            credential_assignment = "pass" + 'word = "' + "releaseSecret123" + '"'
            (root / "README.md").write_text(
                "\n".join(
                    [
                        token,
                        credential_assignment,
                        "/home/" + "amdev" + "/private",
                        fixture,
                        unsupported_claim,
                        draft_label,
                        generated_draft_url,
                        venue_style_benchmark_label,
                        weak_adapter_label,
                        scaffold_label,
                        venue_label,
                        stale_event_name,
                    ]
                ),
                encoding="utf-8",
            )
            (root / "third_party").mkdir()
            (root / "third_party" / "README.md").write_text(third_party_secret, encoding="utf-8")
            (root / "alpabridge.pdf").write_bytes(b"%PDF-1.5\n")

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn("public_hygiene:huggingface_token:README.md", failures)
        self.assertIn("public_hygiene:credential_assignment:README.md", failures)
        self.assertIn("public_hygiene:private_home_path:README.md", failures)
        self.assertIn("public_hygiene:legacy_smoke_fixture:README.md", failures)
        self.assertIn("public_hygiene:outperformance_claim:README.md", failures)
        self.assertIn("public_hygiene:paper_draft_label:README.md", failures)
        self.assertIn("public_hygiene:generated_draft_url:README.md", failures)
        self.assertIn("public_hygiene:venue_style_benchmark_label:README.md", failures)
        self.assertIn("public_hygiene:venue_coupled_process_label:README.md", failures)
        self.assertIn("public_hygiene:weak_adapter_artifact_label:README.md", failures)
        self.assertIn("public_hygiene:weak_artifact_scaffold_label:README.md", failures)
        self.assertIn("public_hygiene:stale_target_event_artifact_name:README.md", failures)
        self.assertIn("public_hygiene:huggingface_token:third_party/README.md", failures)

    def test_community_templates_accept_release_boundary_terms(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative_path, terms in module.COMMUNITY_DOC_REQUIREMENTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(terms), encoding="utf-8")

            failures = module._community_template_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_community_templates_report_missing_release_boundary_terms(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            github = root / ".github"
            github.mkdir()
            (github / "CONTRIBUTING.md").write_text(
                "contract-validation\nintegration failure\npolicy failure\n",
                encoding="utf-8",
            )

            failures = module._community_template_failures(repo_root=root)

        self.assertIn(
            "community_doc_term_missing:.github/CONTRIBUTING.md:claim-valid",
            failures,
        )
        self.assertIn(
            "community_doc_term_missing:.github/CONTRIBUTING.md:restricted assets",
            failures,
        )
        self.assertIn("community_doc_missing:.github/pull_request_template.md", failures)
        self.assertIn("community_doc_missing:.github/ISSUE_TEMPLATE/bug_report.md", failures)

    def test_release_hygiene_reports_duplicate_manuscript_pdfs(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("AlpaBridge release notes\n", encoding="utf-8")
            (root / "alpabridge.pdf").write_bytes(b"%PDF-1.5\n")
            duplicate = root / "paper" / "cvm" / "paper.pdf"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_bytes(b"%PDF-1.5\n")

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn("duplicate_manuscript_pdf:paper/cvm/paper.pdf", failures)

    def test_release_hygiene_reports_public_archive_text_leaks(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = (
                root / "artifacts" / "cvm" / "results" / "public" / "support-bundle.tar.gz"
            )
            archive_path.parent.mkdir(parents=True)
            payload = json.dumps({"path": "/home/" + "amdev" + "/private"}).encode()
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("demo/run-audit.json")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn(
            "public_hygiene_archive:private_home_path:"
            "artifacts/cvm/results/public/support-bundle.tar.gz:demo/run-audit.json",
            failures,
        )

    def test_release_hygiene_reports_public_archive_temp_path_markers(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = (
                root / "artifacts" / "cvm" / "results" / "public" / "support-bundle.tar.gz"
            )
            archive_path.parent.mkdir(parents=True)
            payload = json.dumps({"audit_dir": "<bundle_tmp>/demo/audit"}).encode()
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("demo/run-audit.json")
                info.mtime = module.DETERMINISTIC_ARCHIVE_MTIME
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn(
            "public_hygiene_archive:bundle_tmp_path:"
            "artifacts/cvm/results/public/support-bundle.tar.gz:demo/run-audit.json",
            failures,
        )

    def test_release_hygiene_reports_nondeterministic_public_archive_metadata(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = (
                root / "artifacts" / "cvm" / "results" / "public" / "support-bundle.tar.gz"
            )
            archive_path.parent.mkdir(parents=True)
            payload = b"{}\n"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("demo/run-audit.json")
                info.mtime = module.DETERMINISTIC_ARCHIVE_MTIME + 10
                info.uid = 1000
                info.gid = 1000
                info.uname = "local-user"
                info.gname = "local-group"
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        base = "artifacts/cvm/results/public/support-bundle.tar.gz:demo/run-audit.json"
        self.assertIn(f"public_archive_nondeterministic_metadata:{base}:mtime", failures)
        self.assertIn(f"public_archive_nondeterministic_metadata:{base}:uid", failures)
        self.assertIn(f"public_archive_nondeterministic_metadata:{base}:gid", failures)
        self.assertIn(f"public_archive_nondeterministic_metadata:{base}:uname", failures)
        self.assertIn(f"public_archive_nondeterministic_metadata:{base}:gname", failures)

    def test_release_hygiene_reports_unsafe_public_archive_member_paths(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = (
                root / "artifacts" / "cvm" / "results" / "public" / "support-bundle.tar.gz"
            )
            archive_path.parent.mkdir(parents=True)
            payload = b"{}\n"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("demo/../run-audit.json")
                info.mtime = module.DETERMINISTIC_ARCHIVE_MTIME
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            failures = module._release_hygiene_failures(
                repo_root=root,
                canonical_paper=root / "alpabridge.pdf",
            )

        self.assertIn(
            "public_archive_unsafe_member_path:"
            "artifacts/cvm/results/public/support-bundle.tar.gz:demo/../run-audit.json",
            failures,
        )

    def test_cli_documentation_accepts_documented_scripts_and_make_targets(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "pyproject.toml").write_text(
                "[project.scripts]\n"
                'alpabridge-doctor = "alpabridge.cli.commands.alpabridge_doctor:main"\n'
                'alpabridge-ready = "alpabridge.cli.commands.check_alpasim_readiness:main"\n',
                encoding="utf-8",
            )
            (root / "Makefile").write_text(
                ".PHONY: conformance cvm-check\n",
                encoding="utf-8",
            )
            (root / "docs" / "cli.md").write_text(
                "| `alpabridge-doctor` | Doctor. |\n"
                "| `alpabridge-ready` | Readiness. |\n"
                "| `make conformance` | Test. |\n"
                "| `make cvm-check` | Validate. |\n",
                encoding="utf-8",
            )

            failures = module._cli_documentation_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_cli_documentation_reports_missing_scripts_and_make_targets(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "pyproject.toml").write_text(
                "[project.scripts]\n"
                'alpabridge-doctor = "alpabridge.cli.commands.alpabridge_doctor:main"\n'
                'alpabridge-ready = "alpabridge.cli.commands.check_alpasim_readiness:main"\n',
                encoding="utf-8",
            )
            (root / "Makefile").write_text(
                ".PHONY: conformance cvm-check\n",
                encoding="utf-8",
            )
            (root / "docs" / "cli.md").write_text(
                "| `alpabridge-doctor` | Doctor. |\n| `make conformance` | Test. |\n",
                encoding="utf-8",
            )

            failures = module._cli_documentation_failures(repo_root=root)

        self.assertIn("cli_doc_missing_console_script:docs/cli.md:alpabridge-ready", failures)
        self.assertIn("cli_doc_missing_make_target:docs/cli.md:cvm-check", failures)

    def test_package_metadata_accepts_publication_ready_project_fields(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[project]\n"
                'name = "alpabridge"\n'
                'readme = "README.md"\n'
                'license = "BSD-3-Clause"\n'
                "authors = [\n"
                '    { name = "Alba Maria Tellez Fernandez" },\n'
                "]\n"
                "keywords = [\n"
                '    "autonomous-driving",\n'
                '    "closed-loop-simulation",\n'
                '    "contract-validation",\n'
                '    "system-integration",\n'
                '    "trajectory-policies",\n'
                "]\n"
                "classifiers = [\n"
                '    "Intended Audience :: Science/Research",\n'
                '    "Operating System :: POSIX :: Linux",\n'
                '    "Topic :: Scientific/Engineering",\n'
                "]\n"
                "\n"
                "[project.urls]\n"
                'Homepage = "https://example.com"\n'
                'Repository = "https://example.com/repo"\n'
                'Issues = "https://example.com/issues"\n'
                'Documentation = "https://example.com/docs"\n'
                'Paper = "https://example.com/paper.pdf"\n'
                'Citation = "https://example.com/CITATION.cff"\n',
                encoding="utf-8",
            )

            failures = module._package_metadata_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_package_metadata_reports_missing_publication_fields(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[project]\n"
                'name = "alpabridge"\n'
                'readme = "README.md"\n'
                "keywords = [\n"
                '    "autonomous-driving",\n'
                '    "closed-loop-simulation",\n'
                '    "contract-validation",\n'
                '    "trajectory-policies",\n'
                "]\n"
                "classifiers = [\n"
                '    "Intended Audience :: Science/Research",\n'
                '    "Operating System :: POSIX :: Linux",\n'
                '    "Topic :: Scientific/Engineering",\n'
                "]\n"
                "\n"
                "[project.urls]\n"
                'Homepage = "https://example.com"\n'
                'Repository = "https://example.com/repo"\n'
                'Issues = "https://example.com/issues"\n'
                'Documentation = "https://example.com/docs"\n',
                encoding="utf-8",
            )

            failures = module._package_metadata_failures(repo_root=root)

        self.assertIn("package_metadata_author_missing:pyproject.toml", failures)
        self.assertIn("package_metadata_license_missing:pyproject.toml", failures)
        self.assertIn(
            "package_metadata_keyword_missing:pyproject.toml:system-integration", failures
        )
        self.assertIn("package_metadata_url_missing:pyproject.toml:Paper", failures)
        self.assertIn("package_metadata_url_missing:pyproject.toml:Citation", failures)

    def test_install_reproducibility_accepts_locked_uv_setup(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "pyproject.toml").write_text('[project]\nname = "alpabridge"\n', encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "alpabridge"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            install_text = (
                "```bash\n"
                "uv sync --extra dev\n"
                "uv run alpabridge-doctor --strict-installed --json\n"
                "```\n"
                "The tracked uv.lock dependency snapshot is used.\n"
            )
            (root / "README.md").write_text(install_text, encoding="utf-8")
            (root / "docs" / "getting-started.md").write_text(install_text, encoding="utf-8")

            failures = module._install_reproducibility_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_install_reproducibility_reports_unlocked_or_stale_setup(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "pyproject.toml").write_text('[project]\nname = "alpabridge"\n', encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "other-project"\n',
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                'uv venv .venv\nuv pip install --python .venv/bin/python -e ".[dev]"\n',
                encoding="utf-8",
            )

            failures = module._install_reproducibility_failures(repo_root=root)

        self.assertIn("install_lock_project_missing:uv.lock", failures)
        self.assertIn("install_doc_token_missing:README.md:uv sync --extra dev", failures)
        self.assertIn(
            "install_doc_token_missing:README.md:uv run alpabridge-doctor --strict-installed --json",
            failures,
        )
        self.assertIn("install_doc_token_missing:README.md:uv.lock", failures)
        self.assertIn("install_doc_missing:docs/getting-started.md", failures)

    def test_ci_workflow_accepts_release_gate_surface(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(_valid_ci_workflow_fixture(), encoding="utf-8")

            failures = module._ci_workflow_failures(repo_root=root)

        self.assertEqual([], failures)

    def test_ci_workflow_reports_missing_release_gates(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "on:\n"
                "  push:\n"
                "  pull_request:\n"
                "\n"
                "permissions:\n"
                "  contents: write\n"
                "\n"
                "jobs:\n"
                "  package:\n"
                "    steps:\n"
                "      - uses: actions/checkout@v6\n"
                "      - run: make lint\n",
                encoding="utf-8",
            )

            failures = module._ci_workflow_failures(repo_root=root)

        self.assertIn(
            "ci_workflow_gate_missing:.github/workflows/ci.yml:make paper-verify",
            failures,
        )
        self.assertIn(
            "ci_workflow_gate_missing:.github/workflows/ci.yml:python -m build",
            failures,
        )
        self.assertIn(
            "ci_workflow_gate_missing:.github/workflows/ci.yml:uv sync --extra dev",
            failures,
        )
        self.assertIn("ci_workflow_permissions_not_minimal:.github/workflows/ci.yml", failures)
        self.assertIn("ci_workflow_trigger_missing:.github/workflows/ci.yml", failures)

    def test_manifest_attribution_accepts_integration_blocker(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            (manifest_dir / "blocked.json").write_text(
                json.dumps(
                    {
                        "run_id": "blocked",
                        "status": "blocked",
                        "claim_valid": False,
                        "scene_id": "clipgt-scene",
                        "scenario_category": "available_front_camera_26_02_unclassified",
                        "scene": {
                            "scene_id": "clipgt-scene",
                            "category": "available_front_camera_26_02_unclassified",
                            "scenario_category": "available_front_camera_26_02_unclassified",
                            "selection_rationale": "local cache entry",
                            "asset_availability": "local_usdz_present",
                            "expected_route_feature": "unverified",
                            "expected_interaction_feature": "unverified",
                            "license_gating_status": "gated_asset_referenced_not_redistributed",
                            "categories_verified": False,
                        },
                        "failure_layer": "deployment",
                        "failure_code": "direct_actor_oracle_proxy_missing",
                        "failure_attribution": {
                            "category": "integration_precondition_or_unsupported_contract",
                            "policy_attributable": False,
                            "policy_behavior_attributable": False,
                            "policy_failure_attributable": False,
                            "claim_valid_policy_benchmark": False,
                            "integration_or_evidence_invalid": True,
                            "integration_failure_attributable": True,
                            "interpretation": (
                                "integration_precondition_blocker_not_policy_failure"
                            ),
                            "failure_layer": "deployment",
                            "failure_code": "direct_actor_oracle_proxy_missing",
                            "rule": (
                                "A behavior event, including a policy failure, is "
                                "policy-attributable only after semantic, temporal, "
                                "lifecycle, deployment, and evidence gates pass; "
                                "otherwise the row remains an integration record and "
                                "cannot be counted as a policy failure."
                            ),
                        },
                    }
                ),
                encoding="utf-8",
            )

            failures = module._manifest_attribution_failures(manifest_dir)

        self.assertEqual([], failures)

    def test_manifest_attribution_rejects_policy_attribution_for_blocker(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            (manifest_dir / "blocked.json").write_text(
                json.dumps(
                    {
                        "run_id": "blocked",
                        "status": "blocked",
                        "claim_valid": False,
                        "scene_id": "clipgt-scene",
                        "scenario_category": "available_front_camera_26_02_unclassified",
                        "scene": {
                            "scene_id": "clipgt-scene",
                            "category": "available_front_camera_26_02_unclassified",
                            "scenario_category": "available_front_camera_26_02_unclassified",
                            "selection_rationale": "local cache entry",
                            "asset_availability": "local_usdz_present",
                            "expected_route_feature": "unverified",
                            "expected_interaction_feature": "unverified",
                            "license_gating_status": "gated_asset_referenced_not_redistributed",
                            "categories_verified": False,
                        },
                        "failure_layer": "deployment",
                        "failure_code": "direct_actor_oracle_proxy_missing",
                        "failure_attribution": {
                            "category": "policy_attributable_behavior",
                            "policy_attributable": True,
                            "policy_behavior_attributable": True,
                            "policy_failure_attributable": True,
                            "claim_valid_policy_benchmark": True,
                            "integration_or_evidence_invalid": False,
                            "integration_failure_attributable": False,
                            "interpretation": "policy_behavior_allowed",
                            "failure_layer": "policy",
                            "failure_code": "collision",
                            "rule": "policy result",
                        },
                    }
                ),
                encoding="utf-8",
            )

            failures = module._manifest_attribution_failures(manifest_dir)

        self.assertIn(
            f"failure_attribution_category_mismatch:{manifest_dir / 'blocked.json'}:"
            "blocked:blocked:policy_attributable_behavior",
            failures,
        )
        self.assertIn(
            f"policy_attributable_mismatch:{manifest_dir / 'blocked.json'}:blocked", failures
        )
        self.assertIn(
            f"policy_behavior_attributable_mismatch:{manifest_dir / 'blocked.json'}:blocked",
            failures,
        )
        self.assertIn(
            f"policy_failure_attributable_mismatch:{manifest_dir / 'blocked.json'}:blocked",
            failures,
        )
        self.assertIn(
            f"non_claim_valid_policy_failure_layer:{manifest_dir / 'blocked.json'}:blocked",
            failures,
        )
        self.assertIn(
            f"failure_attribution_layer_mismatch:{manifest_dir / 'blocked.json'}:blocked", failures
        )
        self.assertIn(
            f"failure_attribution_rule_missing:{manifest_dir / 'blocked.json'}:blocked", failures
        )

    def test_manifest_scene_metadata_rejects_missing_and_mismatched_fields(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            missing = module._single_manifest_scene_failures(
                payload={"run_id": "missing", "scene_id": "scene-a"},
                path=path,
                run_id="missing",
            )
            mismatched = module._single_manifest_scene_failures(
                payload={
                    "run_id": "bad",
                    "scene_id": "scene-a",
                    "scenario_category": "turn",
                    "scene": {
                        "scene_id": "scene-b",
                        "category": "straight",
                        "scenario_category": "turn",
                        "selection_rationale": "test",
                        "asset_availability": "public_synthetic",
                        "expected_route_feature": "not_applicable",
                        "expected_interaction_feature": "not_applicable",
                        "license_gating_status": "",
                        "categories_verified": "false",
                    },
                },
                path=path,
                run_id="bad",
            )

        self.assertEqual([f"missing_scene_metadata:{path}:missing"], missing)
        self.assertIn(f"scene_metadata_id_mismatch:{path}:bad", mismatched)
        self.assertIn(f"scenario_category_mismatch:{path}:bad", mismatched)
        self.assertIn(f"scene_metadata_missing_license_status:{path}:bad", mismatched)
        self.assertIn(f"scene_metadata_categories_verified_not_bool:{path}:bad", mismatched)

    def test_frame_schema_accepts_required_public_fields(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            path.write_text(",".join(module.REQUIRED_FRAME_FIELDS) + "\n", encoding="utf-8")

            failures = module._frame_schema_failures(path)

        self.assertEqual([], failures)

    def test_frame_schema_reports_missing_fields(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            path.write_text("run_id,frame_index,route_source\n", encoding="utf-8")

            failures = module._frame_schema_failures(path)

        self.assertTrue(
            any(error.startswith(f"frames_csv_missing_fields:{path}:") for error in failures)
        )
        self.assertIn("camera_count", failures[0])
        self.assertIn("policy_reasoning_status_code", failures[0])


if __name__ == "__main__":
    unittest.main()
