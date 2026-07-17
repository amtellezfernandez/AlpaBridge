from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Pattern
from urllib.parse import unquote

PLACEHOLDERS = ("TODO", "TBD", "FIXME", "RESULTS_PENDING", "[N]", "[M]")
ABSTRACT_MIN_WORDS = 160
ABSTRACT_MAX_WORDS = 210
A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89
PAGE_SIZE_TOLERANCE_PT = 1.0
IEEE_A4_DOCUMENTCLASS_RE = re.compile(
    r"\\documentclass\s*\[\s*conference\s*,\s*a4paper\s*\]\s*\{IEEEtran\}"
)
MANUSCRIPT_LAYOUT_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    (
        "geometry_package",
        re.compile(r"\\usepackage(?:\[[^\]]*\])?\s*\{\s*geometry\s*\}"),
    ),
    (
        "manual_margin_length",
        re.compile(
            r"\\(?:setlength|addtolength)\s*\{\s*\\"
            r"(?:textwidth|textheight|oddsidemargin|evensidemargin|topmargin|"
            r"headheight|headsep|footskip|columnsep|hoffset|voffset)\s*\}"
        ),
    ),
    (
        "manual_page_style",
        re.compile(r"\\(?:thispagestyle|pagestyle|pagenumbering)\s*\{"),
    ),
    (
        "manual_page_counter",
        re.compile(r"\\setcounter\s*\{\s*page\s*\}"),
    ),
    (
        "manual_font_scaling",
        re.compile(
            r"\\(?:fontsize|linespread)\s*\{|"
            r"\\renewcommand\s*\{\s*\\baselinestretch\s*\}"
        ),
    ),
    (
        "negative_spacing",
        re.compile(r"\\[hv]space\*?\s*\{\s*-\s*[\d.]"),
    ),
    (
        "page_enlargement",
        re.compile(r"\\enlargethispage\b"),
    ),
    (
        "template_override",
        re.compile(r"\\IEEEoverridecommandlockouts\b"),
    ),
)
LATEX_LOG_FAILURE_PATTERNS = (
    "Undefined control sequence",
    "Citation `",
    "Reference `",
    "multiply defined",
    "Overfull \\hbox",
    "Underfull \\hbox",
)
REQUIRED_TABLES = (
    "contract_map.tex",
    "main_results.tex",
    "ablations.tex",
    "fault_localization.tex",
    "paper_numbers.tex",
)
REQUIRED_FIGURES = (
    "system_architecture.pdf",
    "evaluation_pipeline.pdf",
    "main_results.pdf",
)
ATTRIBUTION_CATEGORIES = {
    "policy_attributable_behavior",
    "integration_precondition_or_unsupported_contract",
    "integration_runtime_or_evidence_failure",
    "diagnostic_rollout_pending_claim_gate",
    "planned_not_launched",
}
ATTRIBUTION_INTERPRETATIONS = {
    "policy_behavior_allowed",
    "integration_precondition_blocker_not_policy_failure",
    "integration_runtime_or_evidence_failure_not_policy_failure",
    "controlled_contract_diagnostic_not_policy_failure",
    "completed_diagnostic_pending_evidence_gate_not_policy_failure",
    "planned_not_launched_not_policy_failure",
}
REQUIRED_ATTRIBUTION_FIELDS = (
    "category",
    "policy_attributable",
    "policy_behavior_attributable",
    "policy_failure_attributable",
    "claim_valid_policy_benchmark",
    "integration_or_evidence_invalid",
    "integration_failure_attributable",
    "interpretation",
    "failure_layer",
    "failure_code",
    "rule",
)
EXPECTED_ATTRIBUTION_BY_STATUS = {
    "blocked": "integration_precondition_or_unsupported_contract",
    "failed": "integration_runtime_or_evidence_failure",
    "completed": "diagnostic_rollout_pending_claim_gate",
    "planned": "planned_not_launched",
}
REQUIRED_FRAME_FIELDS = (
    "run_id",
    "frame_index",
    "sim_timestamp",
    "observation_timestamp",
    "observation_age_ms",
    "camera_count",
    "route_source",
    "route_waypoint_count",
    "source_trajectory_samples",
    "target_trajectory_samples",
    "trajectory_valid",
    "inference_latency_ms",
    "end_to_end_action_latency_ms",
    "late_message_count",
    "lifecycle_warning_code",
    "policy_reasoning_status_code",
)
REQUIRED_SCENE_FIELDS = (
    "scene_id",
    "category",
    "scenario_category",
    "selection_rationale",
    "asset_availability",
    "expected_route_feature",
    "expected_interaction_feature",
    "license_gating_status",
    "categories_verified",
)
CLAIM_BOUNDARY_README_TERMS = (
    "Failure Attribution Boundary",
    "integration failure",
    "policy failure",
    "policy behavior",
    "not policy failure",
    "claim-valid",
    "Integration/precondition/evidence failure",
)
CLAIM_BOUNDARY_SOURCE_TERMS = (
    "Failure Attribution Rule",
    "integration, precondition, or evidence failure",
    "policy-behavior attribution",
    "policy-failure attribution",
    "\\CVMPolicyBehaviorAttributableRows{}",
    "\\CVMPolicyFailureAttributableRows{}",
    "\\CVMIntegrationFailureAttributableRows{}",
)
README_VISUAL_EXPLANATION_TERMS = (
    "Visual Overview",
    "adapter boundary",
    "not a benchmark result",
    "command-manifest example",
    "valid_claim_evidence",
    "metrics dashboard",
    "RPC timing",
    "service queue depth",
    "rollout duration",
    "step duration",
    "CPU utilization",
    "GPU utilization",
    "GPU memory",
    "service replica counts",
    "do not evaluate policy quality",
)
EVALUATION_STATUS_TERMS = (
    "completed dependency-light closed-loop diagnostic rows",
    "locally available gated scene assets",
    "semantic route-boundary ablations",
    "integration evidence",
    "not as a public policy benchmark",
    "redistributable scene subset",
    "verified scene-category coverage",
    "claim-ready closed-loop policy benchmark",
)
REQUIRED_SUMMARY_ATTRIBUTION_FIELDS = (
    "rule",
    "contract_valid_closed_loop_rows",
    "integration_or_evidence_invalid_closed_loop_rows",
    "precondition_blocked_rows",
    "claim_valid_policy_benchmark_rows",
    "policy_behavior_attributable_rows",
    "policy_failure_attributable_rows",
    "integration_failure_attributable_rows",
    "diagnostic_not_policy_rows",
    "non_policy_attributed_rows",
)
CLAIM_MATRIX_SUMMARY_LINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Configured rows", ("total_rows",)),
    ("Attempted rows", ("attempted_runs",)),
    ("Completed rows", ("completed_runs",)),
    ("Closed-loop completed rows", ("closed_loop_completed_runs",)),
    (
        "Full-contract rows audit-valid",
        (
            "integration_effectiveness.full_contract_audit_valid_runs",
            "integration_effectiveness.full_contract_completed_runs",
        ),
    ),
    (
        "Valid full-contract false-blocked rows",
        (
            "integration_effectiveness.valid_full_contract_false_blocked_runs",
            "integration_effectiveness.valid_full_contract_false_block_denominator",
        ),
    ),
    (
        "Matched semantic metric pairs",
        (
            "integration_effectiveness.semantic_ablation_metric_pairs",
            "integration_effectiveness.semantic_ablation_completed_pairs",
        ),
    ),
    (
        "Command-only rows rejected as non-claim-valid",
        (
            "integration_effectiveness.semantic_ablation_command_proxy_rejected_runs",
            "integration_effectiveness.semantic_ablation_command_proxy_completed_runs",
        ),
    ),
    (
        "Contract-valid closed-loop rows",
        ("failure_attribution.contract_valid_closed_loop_rows",),
    ),
    (
        "Integration/evidence-invalid closed-loop rows",
        ("failure_attribution.integration_or_evidence_invalid_closed_loop_rows",),
    ),
    (
        "Policy-attributable behavior rows",
        ("failure_attribution.policy_behavior_attributable_rows",),
    ),
    (
        "Policy-attributable failure rows",
        ("failure_attribution.policy_failure_attributable_rows",),
    ),
    (
        "Non-policy-attributed rows",
        ("failure_attribution.non_policy_attributed_rows",),
    ),
    (
        "Claim-valid policy benchmark rows",
        ("failure_attribution.claim_valid_policy_benchmark_rows",),
    ),
    ("Planned rows", ("planned_runs",)),
    ("Blocked rows", ("blocked_runs",)),
)
README_SUMMARY_COUNT_SNIPPETS: tuple[tuple[str, str, str], ...] = (
    (
        "policy_behavior_attributable_rows",
        "failure_attribution.policy_behavior_attributable_rows",
        "policy-attributable behavior rows",
    ),
    (
        "policy_failure_attributable_rows",
        "failure_attribution.policy_failure_attributable_rows",
        "policy-attributable failure rows",
    ),
    (
        "integration_failure_attributable_rows",
        "failure_attribution.integration_failure_attributable_rows",
        "integration/precondition blocker rows",
    ),
    (
        "diagnostic_not_policy_rows",
        "failure_attribution.diagnostic_not_policy_rows",
        "completed diagnostic rows",
    ),
)
PAPER_NUMBER_JSON_FIELDS: tuple[tuple[str, str], ...] = (
    ("CVMTotalRows", "total_rows"),
    ("CVMPlannedRuns", "planned_runs"),
    ("CVMAttemptedRuns", "attempted_runs"),
    ("CVMCompletedRuns", "completed_runs"),
    ("CVMSyntheticCompletedRuns", "synthetic_completed_runs"),
    ("CVMClosedLoopCompletedRuns", "closed_loop_completed_runs"),
    ("CVMClosedLoopAuditValidRuns", "closed_loop_audit_valid_runs"),
    ("CVMClosedLoopMetricRows", "closed_loop_metric_rows"),
    ("CVMFullContractCompletedRuns", "integration_effectiveness.full_contract_completed_runs"),
    ("CVMFullContractAuditValidRuns", "integration_effectiveness.full_contract_audit_valid_runs"),
    (
        "CVMValidFullContractFalseBlockedRuns",
        "integration_effectiveness.valid_full_contract_false_blocked_runs",
    ),
    (
        "CVMValidFullContractFalseBlockDenominator",
        "integration_effectiveness.valid_full_contract_false_block_denominator",
    ),
    ("CVMContractValidClosedLoopRows", "failure_attribution.contract_valid_closed_loop_rows"),
    (
        "CVMIntegrationInvalidClosedLoopRows",
        "failure_attribution.integration_or_evidence_invalid_closed_loop_rows",
    ),
    (
        "CVMClaimValidPolicyBenchmarkRows",
        "failure_attribution.claim_valid_policy_benchmark_rows",
    ),
    (
        "CVMPolicyBehaviorAttributableRows",
        "failure_attribution.policy_behavior_attributable_rows",
    ),
    (
        "CVMPolicyFailureAttributableRows",
        "failure_attribution.policy_failure_attributable_rows",
    ),
    (
        "CVMIntegrationFailureAttributableRows",
        "failure_attribution.integration_failure_attributable_rows",
    ),
    ("CVMDiagnosticNotPolicyRows", "failure_attribution.diagnostic_not_policy_rows"),
    ("CVMNonPolicyAttributedRows", "failure_attribution.non_policy_attributed_rows"),
    ("CVMSyntheticDiagnosticRows", "failure_attribution.synthetic_diagnostic_rows"),
    (
        "CVMSemanticAblationCompletedPairs",
        "integration_effectiveness.semantic_ablation_completed_pairs",
    ),
    (
        "CVMSemanticAblationMetricPairs",
        "integration_effectiveness.semantic_ablation_metric_pairs",
    ),
    (
        "CVMCommandProxyCompletedRuns",
        "integration_effectiveness.semantic_ablation_command_proxy_completed_runs",
    ),
    (
        "CVMCommandProxyRejectedRuns",
        "integration_effectiveness.semantic_ablation_command_proxy_rejected_runs",
    ),
    ("CVMFailedRuns", "failed_runs"),
    ("CVMBlockedRuns", "blocked_runs"),
    ("CVMSyntheticRuns", "synthetic_completed_runs"),
    ("CVMCoreRows", "matrix_counts.core"),
    ("CVMSemanticRows", "matrix_counts.semantic_ablation"),
    ("CVMTemporalRows", "matrix_counts.temporal_ablation"),
    ("CVMLifecycleRows", "matrix_counts.lifecycle_stress"),
    ("CVMFaultRows", "matrix_counts.fault_injection"),
)
PAPER_NUMBER_FLOAT_FIELDS: tuple[tuple[str, str], ...] = (
    (
        "CVMSemanticProgressDeltaMean",
        "semantic_ablation_deltas.progress.mean_delta_full_minus_command_only",
    ),
    (
        "CVMSemanticProgressRelDeltaMean",
        "semantic_ablation_deltas.progress_rel.mean_delta_full_minus_command_only",
    ),
    (
        "CVMSemanticOffroadDeltaMean",
        "semantic_ablation_deltas.offroad.mean_delta_full_minus_command_only",
    ),
    (
        "CVMSemanticCollisionAnyDeltaMean",
        "semantic_ablation_deltas.collision_any.mean_delta_full_minus_command_only",
    ),
    (
        "CVMSemanticPlanDeviationDeltaMean",
        "semantic_ablation_deltas.plan_deviation.mean_delta_full_minus_command_only",
    ),
    ("CVMClosedLoopCollisionAnyMean", "closed_loop_metrics.collision_any.mean"),
    ("CVMClosedLoopOffroadMean", "closed_loop_metrics.offroad.mean"),
    ("CVMClosedLoopProgressMean", "closed_loop_metrics.progress.mean"),
)
GENERATED_TABLE_JSON_FIELDS: tuple[str, ...] = (
    "total_rows",
    "completed_runs",
    "planned_runs",
    "blocked_runs",
    "integration_effectiveness.full_contract_completed_runs",
    "integration_effectiveness.full_contract_audit_valid_runs",
    "integration_effectiveness.valid_full_contract_false_blocked_runs",
    "integration_effectiveness.valid_full_contract_false_block_denominator",
    "integration_effectiveness.semantic_ablation_completed_pairs",
    "integration_effectiveness.semantic_ablation_metric_pairs",
    "integration_effectiveness.semantic_ablation_command_proxy_completed_runs",
    "integration_effectiveness.semantic_ablation_command_proxy_rejected_runs",
    "failure_attribution.policy_behavior_attributable_rows",
    "failure_attribution.policy_failure_attributable_rows",
    "failure_attribution.integration_failure_attributable_rows",
)
PAPER_NUMBER_LIFECYCLE_ADAPTERS: tuple[tuple[str, str], ...] = (
    ("Full", "full_lifecycle_hardening"),
    ("Strict", "strict_or_pre_hardening_behavior"),
)
REQUIRED_METADATA_FIELDS = (
    "title",
    "author",
    "affiliation",
    "pdf_subject",
    "abstract_source_sha256",
    "abstract_word_count",
)
REQUIRED_PROJECT_KEYWORDS = (
    "autonomous-driving",
    "closed-loop-simulation",
    "contract-validation",
    "system-integration",
    "trajectory-policies",
)
REQUIRED_PROJECT_CLASSIFIERS = (
    "Intended Audience :: Science/Research",
    "Operating System :: POSIX :: Linux",
    "Topic :: Scientific/Engineering",
)
REQUIRED_PROJECT_URLS = (
    "Homepage",
    "Repository",
    "Issues",
    "Documentation",
    "Paper",
    "Citation",
)
REQUIRED_CI_WORKFLOW_TOKENS = (
    "actions/checkout@",
    "actions/setup-python@",
    "astral-sh/setup-uv@",
    "make lint",
    "make conformance",
    "make coverage",
    "make smoke",
    "python -m build",
    "wod2sim-doctor --strict-installed --json",
    "wod2sim-build-oracle-proxy --help",
    "wod2sim-batch",
    "make paper-verify",
    "qpdf --check wod2sim.pdf",
    "pdfinfo wod2sim.pdf",
    "pdffonts wod2sim.pdf",
    "actions/upload-artifact@",
)
PUBLIC_SCAN_PATHS = (
    "README.md",
    "CITATION.cff",
    "LICENSE",
    "LICENSES",
    "docs",
    "paper",
    "scripts",
    "artifacts/cvm",
    ".github",
    "Makefile",
    "pyproject.toml",
    "src",
    "tests",
    "configs",
    "third_party",
)
PUBLIC_SCAN_SKIP_PARTS = (
    ("artifacts", "cvm", "results", "core_probe"),
    ("artifacts", "cvm", "logs"),
    ("artifacts", "cvm", "results", "demo"),
)
PUBLIC_SCAN_SKIP_NAMES = {"run_dirs"}
TEXT_SKIP_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".gz",
    ".zip",
    ".tar",
    ".pyc",
}
FONT_REF_RE = re.compile(r":\s+[^\n']*'([^']+)'\s+\((\d+)\s+0\s+R\)")
FONT_DESCRIPTOR_RE = re.compile(r"/FontDescriptor\s+(\d+)\s+0\s+R")
DESCENDANT_FONT_RE = re.compile(r"/DescendantFonts\s*\[\s*((?:\d+\s+0\s+R\s*)+)\]")
OBJECT_REF_RE = re.compile(r"(\d+)\s+0\s+R")
EMBEDDED_FONT_FILE_RE = re.compile(r"/FontFile(?:2|3)?\b")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HTML_LOCAL_REF_RE = re.compile(r"\b(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
HTML_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_ALT_ATTR_RE = re.compile(r"\balt\s*=\s*(['\"])(.*?)\1", re.IGNORECASE)
ARCHIVE_TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".csv",
    ".txt",
    ".md",
    ".sh",
    ".yaml",
    ".yml",
    ".log",
}
FORBIDDEN_TEXT_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    ("private_password", re.compile(re.escape("Marso" + "123"))),
    ("huggingface_token", re.compile(r"hf_[A-Za-z0-9]{20,}")),
    ("private_home_path", re.compile(r"/home/(?!user\b|\.\.\.)([A-Za-z0-9_.-]+)")),
    ("private_host", re.compile(r"\bMARSO-PC\b")),
    ("legacy_smoke_fixture", re.compile(r"\b" + "spot" + r"light_reflex\b", re.IGNORECASE)),
    ("legacy_smoke_claim", re.compile(r"\b" + "Spot" + r"light\b")),
    ("claim_valid_true_text", re.compile(r"\bclaim_valid\s*=\s*true\b")),
    ("valid_claim_evidence_true_text", re.compile(r"\bvalid_claim_evidence:\s*true\b")),
    ("state_of_the_art_claim", re.compile(r"\bstate[\s-]+of[\s-]+the[\s-]+art\b", re.IGNORECASE)),
    ("significant_improvement_claim", re.compile(r"\bsignificant\s+improvement\b", re.IGNORECASE)),
    ("outperformance_claim", re.compile(r"\bwe\s+outperform\b", re.IGNORECASE)),
    ("sota_claim", re.compile(r"\bSOTA\b")),
    ("paper_draft_label", re.compile(r"\bpaper\s+draft\b", re.IGNORECASE)),
    ("generated_draft_url", re.compile(r"\bauto[-_]draft[-_/0-9A-Za-z]*\b", re.IGNORECASE)),
    ("venue_coupled_process_label", re.compile(r"\bvenue[-\s]+specific\b", re.IGNORECASE)),
    (
        "venue_style_benchmark_label",
        re.compile(
            r"\b(?:"
            + "|".join(
                (
                    "Neur" + "IPS",
                    chr(83) + chr(73) + chr(73),
                    "IC" + "LR",
                    "IC" + "ML",
                    "CV" + "PR",
                    "IC" + "RA",
                    "IR" + "OS",
                )
            )
            + r")[-\s]+style\s+benchmark\b"
        ),
    ),
    (
        "process_translation_reference",
        re.compile(
            r"\b(?:neutral\s+)?"
            + "cv"
            + "m"
            + r"\s+"
            + "equivalence"
            + r"\s+"
            + "map"
            + r"\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prior_process_reference",
        re.compile(r"\b" + "old" + r"\s+" + "layou" + r"[rt]\b", re.IGNORECASE),
    ),
    (
        "internal_process_package_reference",
        re.compile(
            r"\b(?:"
            + "old"
            + r"\s+)?"
            + "internal"
            + r"\s+"
            + "deliverable"
            + r"\s+"
            + "layout"
            + r"\b",
            re.IGNORECASE,
        ),
    ),
    ("weak_adapter_artifact_label", re.compile(r"\badapter\s+and\s+evaluation\s+artifact\b", re.IGNORECASE)),
    ("weak_artifact_scaffold_label", re.compile(r"\bartifact\s+scaffold\b", re.IGNORECASE)),
    (
        "stale_target_event_artifact_name",
        re.compile(
            r"\b"
            + chr(115)
            + chr(105)
            + chr(105)
            + r"2027\b|\b"
            + chr(83)
            + chr(73)
            + chr(73)
            + r"\s+2027\b",
            re.IGNORECASE,
        ),
    ),
)
DUPLICATE_MANUSCRIPT_PDFS = (
    "paper.pdf",
    "paper/paper.pdf",
    "paper/cvm/paper.pdf",
    "paper/cvm/main.pdf",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the WOD2Sim paper release package.")
    parser.add_argument("--paper", default=Path("wod2sim.pdf"), type=Path)
    parser.add_argument("--source", default=Path("paper/cvm"), type=Path)
    parser.add_argument("--results", default=Path("artifacts/cvm/results"), type=Path)
    parser.add_argument("--tables", default=Path("artifacts/cvm/tables"), type=Path)
    parser.add_argument("--figures", default=Path("artifacts/cvm/figures"), type=Path)
    parser.add_argument("--metadata", default=None, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--max-pages", default=6, type=int)
    parser.add_argument("--allow-eight-pages", action="store_true")
    args = parser.parse_args()

    failures: list[str] = []
    paper_info = ""
    if not args.paper.is_file():
        failures.append(f"missing_pdf:{args.paper}")
    else:
        size = args.paper.stat().st_size
        if size > 6 * 1024 * 1024:
            failures.append(f"pdf_too_large:{size}")
        paper_info = _mutool_info(args.paper)
        pages = _extract_pages(paper_info)
        if pages is None:
            failures.append("page_count_unavailable")
        else:
            max_pages = 8 if args.allow_eight_pages else args.max_pages
            if pages < 4 or pages > max_pages:
                failures.append(f"page_count_out_of_range:{pages}")
        failures.extend(_pdf_a4_page_size_failures(info=paper_info, path=args.paper))
        if not re.search(r"/Title(?:<[^>]+>|\([^)]+\))", paper_info):
            failures.append("pdf_title_metadata_missing")
        if not re.search(r"/Author(?:<[^>]+>|\([^)]+\))", paper_info):
            failures.append("pdf_author_metadata_missing")
        failures.extend(_pdf_font_embedding_failures(args.paper))

    main_tex = args.source / "main.tex"
    metadata_path = args.metadata if args.metadata is not None else args.source / "metadata.json"
    metadata, metadata_failures = _load_paper_metadata(metadata_path)
    failures.extend(metadata_failures)
    source_text = main_tex.read_text(encoding="utf-8", errors="ignore") if main_tex.is_file() else ""
    failures.extend(
        _paper_metadata_text_failures(
            metadata=metadata,
            metadata_path=metadata_path,
            source_text=source_text,
            source_path=main_tex,
        )
    )
    failures.extend(
        _pdf_metadata_text_failures(
            metadata=metadata,
            metadata_path=metadata_path,
            paper_info=paper_info,
            paper_path=args.paper,
        )
    )
    failures.extend(_source_text_failures(source_text=source_text, path=main_tex))
    readme_path = args.repo_root / "README.md"
    readme_text = (
        readme_path.read_text(encoding="utf-8", errors="ignore")
        if readme_path.is_file()
        else ""
    )
    failures.extend(
        _claim_boundary_text_failures(
            readme_text=readme_text,
            readme_path=readme_path,
            source_text=source_text,
            source_path=main_tex,
        )
    )
    failures.extend(
        _readme_visual_explanation_failures(
            readme_text=readme_text,
            readme_path=readme_path,
        )
    )
    evaluation_path = args.repo_root / "docs" / "evaluation.md"
    evaluation_text = (
        evaluation_path.read_text(encoding="utf-8", errors="ignore")
        if evaluation_path.is_file()
        else ""
    )
    failures.extend(
        _evaluation_status_failures(
            evaluation_text=evaluation_text,
            evaluation_path=evaluation_path,
        )
    )

    for path in sorted(args.source.rglob("*.tex")) + sorted(args.source.rglob("*.bib")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in PLACEHOLDERS:
            if token in text:
                failures.append(f"placeholder:{path}:{token}")
        if re.search(r"/home/[A-Za-z0-9_.-]+", text):
            failures.append(f"private_path:{path}")

    log = args.source / "main.log"
    failures.extend(_latex_log_failures(log))

    data_hash = _load_summary_data_hash(args.results / "summary.json")
    if data_hash is None:
        failures.append("missing_or_invalid_summary_data_hash")
    else:
        failures.extend(_summary_attribution_failures(args.results / "summary.json"))
        failures.extend(
            _readme_summary_count_failures(
                readme_text=readme_text,
                readme_path=readme_path,
                summary_path=args.results / "summary.json",
            )
        )
        failures.extend(
            _generated_artifact_failures(
                data_hash=data_hash,
                table_dirs=(args.tables, args.source / "generated"),
                figure_dirs=(args.figures, args.source / "figures"),
            )
        )
        failures.extend(
            _paper_generated_copy_failures(
                canonical_tables=args.tables,
                paper_tables=args.source / "generated",
                canonical_figures=args.figures,
                paper_figures=args.source / "figures",
            )
        )
        failures.extend(
            _paper_number_macro_failures(
                summary_path=args.results / "summary.json",
                paper_numbers_path=args.tables / "paper_numbers.tex",
                lifecycle_path=args.results / "lifecycle_stress" / "lifecycle_stress.csv",
                fault_path=args.results / "fault_injection.csv",
            )
        )
        failures.extend(
            _generated_table_value_failures(
                tables=args.tables,
                summary_path=args.results / "summary.json",
                lifecycle_path=args.results / "lifecycle_stress" / "lifecycle_stress.csv",
                fault_path=args.results / "fault_injection.csv",
            )
        )
    failures.extend(_frame_schema_failures(args.results / "frames.csv"))
    failures.extend(
        _claim_evidence_matrix_failures(
            matrix_path=args.results.parent / "reports" / "claim_evidence_matrix.md",
            summary_path=args.results / "summary.json",
        )
    )
    failures.extend(_manifest_attribution_failures(args.results.parent / "manifests" / "run_manifests"))
    failures.extend(
        _release_hygiene_failures(repo_root=args.repo_root, canonical_paper=args.paper)
    )

    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("WOD2Sim paper validation passed")
    return 0


def _mutool_info(path: Path) -> str:
    result = subprocess.run(
        ["mutool", "info", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _mutool_info_fonts(path: Path) -> str:
    result = subprocess.run(
        ["mutool", "info", "-F", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _mutool_show(path: Path, object_id: str) -> str:
    result = subprocess.run(
        ["mutool", "show", str(path), object_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _extract_pages(info: str) -> int | None:
    match = re.search(r"Pages:\s+(\d+)", info)
    return None if match is None else int(match.group(1))


def _pdf_a4_page_size_failures(*, info: str, path: Path) -> list[str]:
    mediaboxes = _extract_mediaboxes(info)
    if not mediaboxes:
        return [f"page_size_unavailable:{path}"]
    failures: list[str] = []
    for index, (x0, y0, x1, y1) in enumerate(mediaboxes, start=1):
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        if not (
            _within_tolerance(width, A4_WIDTH_PT)
            and _within_tolerance(height, A4_HEIGHT_PT)
        ):
            failures.append(f"page_size_not_a4:{path}:{index}:{width:.3f}x{height:.3f}")
    return failures


def _extract_mediaboxes(info: str) -> list[tuple[float, float, float, float]]:
    mediaboxes: list[tuple[float, float, float, float]] = []
    for line in info.splitlines():
        if "[" not in line or "]" not in line:
            continue
        values = re.findall(r"-?\d+(?:\.\d+)?", line[line.find("[") : line.rfind("]") + 1])
        if len(values) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in values)
        mediaboxes.append((x0, y0, x1, y1))
    return mediaboxes


def _within_tolerance(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= PAGE_SIZE_TOLERANCE_PT


def _load_summary_data_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    data_hash = payload.get("data_hash")
    return data_hash if isinstance(data_hash, str) and data_hash else None


def _load_paper_metadata(path: Path) -> tuple[dict[str, object], list[str]]:
    if not path.is_file():
        return {}, [f"missing_paper_metadata:{path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, [f"invalid_paper_metadata_json:{path}"]
    if not isinstance(payload, dict):
        return {}, [f"invalid_paper_metadata_type:{path}"]
    failures: list[str] = []
    for field in REQUIRED_METADATA_FIELDS:
        value = payload.get(field)
        if field == "abstract_word_count":
            if not isinstance(value, int):
                failures.append(f"paper_metadata_field_missing:{path}:{field}")
        elif not isinstance(value, str) or not value.strip():
            failures.append(f"paper_metadata_field_missing:{path}:{field}")
    return payload, failures


def _source_text_failures(*, source_text: str, path: Path) -> list[str]:
    failures: list[str] = []
    active_source = _strip_latex_comments(source_text)
    if not IEEE_A4_DOCUMENTCLASS_RE.search(active_source):
        failures.append(f"source_documentclass_not_ieee_a4:{path}")
    failures.extend(_source_layout_failures(source_text=source_text, path=path))
    abstract_words = _abstract_word_count(source_text)
    if abstract_words is None:
        failures.append(f"missing_abstract:{path}")
    elif abstract_words < ABSTRACT_MIN_WORDS or abstract_words > ABSTRACT_MAX_WORDS:
        failures.append(f"abstract_word_count_out_of_range:{path}:{abstract_words}")
    if re.search(r"pdfsubject\s*=\s*\{[^}]*\bdraft\b", source_text, re.IGNORECASE):
        failures.append(f"source_pdfsubject_marked_draft:{path}")
    return failures


def _source_layout_failures(*, source_text: str, path: Path) -> list[str]:
    active_source = _strip_latex_comments(source_text)
    failures: list[str] = []
    for label, pattern in MANUSCRIPT_LAYOUT_PATTERNS:
        if pattern.search(active_source):
            failures.append(f"source_layout_hack:{path}:{label}")
    return failures


def _latex_log_failures(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [f"latex_log_warning:{pattern}" for pattern in LATEX_LOG_FAILURE_PATTERNS if pattern in text]


def _paper_metadata_text_failures(
    *,
    metadata: dict[str, object],
    metadata_path: Path,
    source_text: str,
    source_path: Path,
) -> list[str]:
    if not metadata:
        return []
    failures: list[str] = []
    expected_title = str(metadata.get("title", ""))
    expected_author = str(metadata.get("author", ""))
    expected_affiliation = str(metadata.get("affiliation", ""))
    expected_pdf_subject = str(metadata.get("pdf_subject", ""))
    title = _latex_command_value(source_text, "title")
    pdf_title = _hypersetup_value(source_text, "pdftitle")
    pdf_author = _hypersetup_value(source_text, "pdfauthor")
    pdf_subject = _hypersetup_value(source_text, "pdfsubject")
    author = _latex_command_value(source_text, "IEEEauthorblockN")
    if title != expected_title:
        failures.append(f"metadata_title_mismatch:{source_path}:{metadata_path}")
    if pdf_title != expected_title:
        failures.append(f"metadata_pdf_title_mismatch:{source_path}:{metadata_path}")
    if author != expected_author:
        failures.append(f"metadata_author_mismatch:{source_path}:{metadata_path}")
    if pdf_author != expected_author:
        failures.append(f"metadata_pdf_author_mismatch:{source_path}:{metadata_path}")
    if expected_affiliation not in source_text:
        failures.append(f"metadata_affiliation_missing:{source_path}:{metadata_path}")
    if pdf_subject != expected_pdf_subject:
        failures.append(f"metadata_pdf_subject_mismatch:{source_path}:{metadata_path}")
    failures.extend(
        _paper_abstract_metadata_failures(
            metadata=metadata,
            metadata_path=metadata_path,
            source_text=source_text,
            source_path=source_path,
        )
    )
    return failures


def _pdf_metadata_text_failures(
    *,
    metadata: dict[str, object],
    metadata_path: Path,
    paper_info: str,
    paper_path: Path,
) -> list[str]:
    if not metadata or not paper_info:
        return []
    failures: list[str] = []
    expected = {
        "Title": str(metadata.get("title", "")),
        "Author": str(metadata.get("author", "")),
        "Subject": str(metadata.get("pdf_subject", "")),
    }
    for key, expected_value in expected.items():
        actual_value = _pdf_info_text_value(paper_info, key)
        if actual_value is None:
            failures.append(f"pdf_metadata_field_missing:{paper_path}:{key}")
            continue
        if actual_value != expected_value:
            failures.append(f"pdf_metadata_field_mismatch:{paper_path}:{metadata_path}:{key}")
    return failures


def _pdf_info_text_value(info: str, key: str) -> str | None:
    match = re.search(
        rf"/{re.escape(key)}(?P<value><[0-9A-Fa-f\s]*>|\((?:\\.|[^\\)])*\))",
        info,
        re.DOTALL,
    )
    if match is None:
        return None
    return _decode_pdf_string(match.group("value"))


def _decode_pdf_string(value: str) -> str:
    if value.startswith("<") and value.endswith(">"):
        hex_text = re.sub(r"\s+", "", value[1:-1])
        try:
            raw = bytes.fromhex(hex_text)
        except ValueError:
            return ""
        for encoding in ("utf-16", "utf-16-be", "utf-8", "latin-1"):
            try:
                return raw.decode(encoding).strip("\ufeff")
            except UnicodeDecodeError:
                continue
        return ""
    if value.startswith("(") and value.endswith(")"):
        literal = value[1:-1]
        literal = literal.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
        return literal
    return value


def _paper_abstract_metadata_failures(
    *,
    metadata: dict[str, object],
    metadata_path: Path,
    source_text: str,
    source_path: Path,
) -> list[str]:
    abstract = _abstract_body(source_text)
    if abstract is None:
        return [f"metadata_abstract_missing:{source_path}:{metadata_path}"]
    actual_hash = _sha256_text(_normalize_latex_source(abstract))
    expected_hash = str(metadata.get("abstract_source_sha256", ""))
    failures: list[str] = []
    if actual_hash != expected_hash:
        failures.append(f"metadata_abstract_hash_mismatch:{source_path}:{metadata_path}")
    actual_words = _abstract_word_count(source_text)
    expected_words = metadata.get("abstract_word_count")
    if actual_words != expected_words:
        failures.append(
            f"metadata_abstract_word_count_mismatch:{source_path}:{metadata_path}:"
            f"{actual_words}:{expected_words}"
        )
    return failures


def _latex_command_value(source_text: str, command: str) -> str:
    match = re.search(rf"\\{re.escape(command)}\{{([^{{}}]*)\}}", source_text, re.DOTALL)
    if match is None:
        return ""
    return _normalize_latex_source(match.group(1))


def _hypersetup_value(source_text: str, key: str) -> str:
    match = re.search(rf"{re.escape(key)}\s*=\s*\{{([^{{}}]*)\}}", source_text, re.DOTALL)
    if match is None:
        return ""
    return _normalize_latex_source(match.group(1))


def _abstract_body(source_text: str) -> str | None:
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", source_text, re.DOTALL)
    return None if match is None else match.group(1)


def _normalize_latex_source(text: str) -> str:
    text = _strip_latex_comments(text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_latex_comments(text: str) -> str:
    return re.sub(r"(?m)(?<!\\)%.*$", "", text)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pdf_font_embedding_failures(path: Path) -> list[str]:
    font_info = _mutool_info_fonts(path)
    if not font_info:
        return [f"font_list_unavailable:{path}"]
    fonts = _extract_pdf_fonts(font_info)
    if not fonts:
        return [f"font_list_empty:{path}"]
    failures: list[str] = []
    for font_name, object_id in fonts:
        status, failure_object = _embedded_font_status(path, object_id, visited=set())
        if status == "ok":
            continue
        failures.append(f"{status}:{path}:{font_name}:{failure_object}")
    return failures


def _extract_pdf_fonts(font_info: str) -> list[tuple[str, str]]:
    fonts: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in FONT_REF_RE.finditer(font_info):
        font = (match.group(1), match.group(2))
        if font in seen:
            continue
        seen.add(font)
        fonts.append(font)
    return fonts


def _embedded_font_status(
    path: Path,
    object_id: str,
    *,
    visited: set[str],
) -> tuple[str, str]:
    if object_id in visited:
        return ("font_descriptor_missing", object_id)
    visited.add(object_id)
    font_object = _mutool_show(path, object_id)
    if not font_object:
        return ("font_object_unavailable", object_id)
    if EMBEDDED_FONT_FILE_RE.search(font_object):
        return ("ok", object_id)
    descriptor_ids = FONT_DESCRIPTOR_RE.findall(font_object)
    if descriptor_ids:
        for descriptor_id in descriptor_ids:
            descriptor = _mutool_show(path, descriptor_id)
            if not descriptor:
                return ("font_descriptor_unavailable", descriptor_id)
            if EMBEDDED_FONT_FILE_RE.search(descriptor):
                return ("ok", descriptor_id)
        return ("font_not_embedded", descriptor_ids[0])
    for descendant_group in DESCENDANT_FONT_RE.findall(font_object):
        for descendant_id in OBJECT_REF_RE.findall(descendant_group):
            status, failure_object = _embedded_font_status(
                path,
                descendant_id,
                visited=visited,
            )
            if status == "ok":
                return ("ok", failure_object)
            if status != "font_descriptor_missing":
                return (status, failure_object)
    return ("font_descriptor_missing", object_id)


def _claim_boundary_text_failures(
    *,
    readme_text: str,
    readme_path: Path,
    source_text: str,
    source_path: Path,
) -> list[str]:
    failures: list[str] = []
    for term in CLAIM_BOUNDARY_README_TERMS:
        if not _contains_claim_term(readme_text, term):
            failures.append(f"claim_boundary_readme_missing:{readme_path}:{term}")
    for term in CLAIM_BOUNDARY_SOURCE_TERMS:
        if not _contains_claim_term(source_text, term):
            failures.append(f"claim_boundary_source_missing:{source_path}:{term}")
    return failures


def _readme_visual_explanation_failures(*, readme_text: str, readme_path: Path) -> list[str]:
    failures: list[str] = []
    for term in README_VISUAL_EXPLANATION_TERMS:
        if not _contains_claim_term(readme_text, term):
            failures.append(f"readme_visual_explanation_missing:{readme_path}:{term}")
    return failures


def _evaluation_status_failures(*, evaluation_text: str, evaluation_path: Path) -> list[str]:
    failures: list[str] = []
    for term in EVALUATION_STATUS_TERMS:
        if not _contains_claim_term(evaluation_text, term):
            failures.append(f"evaluation_status_missing:{evaluation_path}:{term}")
    return failures


def _contains_claim_term(text: str, term: str) -> bool:
    normalized_text = re.sub(r"\s+", " ", text)
    normalized_term = re.sub(r"\s+", " ", term)
    if "\\" in term:
        return normalized_term in normalized_text
    return normalized_term.lower() in normalized_text.lower()


def _abstract_word_count(source_text: str) -> int | None:
    abstract = _abstract_body(source_text)
    if abstract is None:
        return None
    abstract = re.sub(r"%.*", "", abstract)
    abstract = abstract.replace(r"\_", "_")
    abstract = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{\}", " number ", abstract)
    abstract = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r" \1 ", abstract)
    abstract = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", abstract)
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", abstract))


def _summary_attribution_failures(path: Path) -> list[str]:
    failures: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [f"summary_attribution_unreadable:{path}"]
    total_rows = payload.get("total_rows")
    attribution = payload.get("failure_attribution")
    if not isinstance(attribution, dict):
        return [f"summary_attribution_missing:{path}"]
    for field in REQUIRED_SUMMARY_ATTRIBUTION_FIELDS:
        if field not in attribution:
            failures.append(f"summary_attribution_field_missing:{path}:{field}")
    rule = str(attribution.get("rule", ""))
    for term in ("policy failure", "semantic", "temporal", "lifecycle", "deployment", "evidence"):
        if term not in rule:
            failures.append(f"summary_attribution_rule_missing:{path}:{term}")
    policy_behavior = _summary_int(attribution, "policy_behavior_attributable_rows")
    policy_failure = _summary_int(attribution, "policy_failure_attributable_rows")
    claim_valid_policy = _summary_int(attribution, "claim_valid_policy_benchmark_rows")
    non_policy = _summary_int(attribution, "non_policy_attributed_rows")
    if policy_failure > policy_behavior:
        failures.append(f"summary_policy_failure_exceeds_behavior:{path}")
    if claim_valid_policy != policy_behavior:
        failures.append(f"summary_claim_valid_policy_behavior_mismatch:{path}")
    if isinstance(total_rows, int) and non_policy + policy_behavior != total_rows:
        failures.append(f"summary_policy_attribution_partition_mismatch:{path}")
    return failures


def _readme_summary_count_failures(
    *,
    readme_text: str,
    readme_path: Path,
    summary_path: Path,
) -> list[str]:
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [f"readme_summary_unreadable:{summary_path}"]
    if not isinstance(summary, dict):
        return [f"readme_summary_invalid:{summary_path}"]

    failures: list[str] = []
    for label, dotted_path, suffix in README_SUMMARY_COUNT_SNIPPETS:
        value = _json_path_value(summary, dotted_path)
        if not isinstance(value, int):
            failures.append(f"readme_summary_field_missing:{summary_path}:{dotted_path}")
            continue
        expected = f"`{value}` {suffix}"
        if not _contains_claim_term(readme_text, expected):
            failures.append(f"readme_summary_count_mismatch:{readme_path}:{label}:{expected}")
    return failures


def _claim_evidence_matrix_failures(*, matrix_path: Path, summary_path: Path) -> list[str]:
    if not matrix_path.is_file():
        return [f"missing_claim_evidence_matrix:{matrix_path}"]
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [f"claim_evidence_summary_unreadable:{summary_path}"]
    if not isinstance(summary, dict):
        return [f"claim_evidence_summary_invalid:{summary_path}"]
    text = matrix_path.read_text(encoding="utf-8", errors="ignore")
    failures: list[str] = []
    for label, value_paths in CLAIM_MATRIX_SUMMARY_LINES:
        expected_values = [_claim_matrix_summary_value(summary, path) for path in value_paths]
        if any(value is None for value in expected_values):
            failures.append(f"claim_evidence_summary_field_missing:{summary_path}:{label}")
            continue
        expected_value = "/".join(str(value) for value in expected_values)
        expected_line = f"- {label}: {expected_value}."
        if expected_line not in text:
            failures.append(f"claim_evidence_matrix_count_mismatch:{matrix_path}:{label}:{expected_value}")
    if "`artifacts/cvm/results/summary.json`" not in text:
        failures.append(f"claim_evidence_matrix_missing_summary_artifact:{matrix_path}")
    return failures


def _claim_matrix_summary_value(summary: dict[str, object], dotted_path: str) -> int | None:
    value: object = summary
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value if isinstance(value, int) else None


def _generated_artifact_failures(
    *, data_hash: str, table_dirs: tuple[Path, ...], figure_dirs: tuple[Path, ...]
) -> list[str]:
    failures: list[str] = []
    expected_marker = f"data_hash={data_hash}"
    for table_dir in table_dirs:
        for name in REQUIRED_TABLES:
            path = table_dir / name
            if not path.is_file():
                failures.append(f"missing_generated_table:{path}")
                continue
            first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:1]
            if not first_line or expected_marker not in first_line[0]:
                failures.append(f"generated_table_hash_mismatch:{path}")
    for figure_dir in figure_dirs:
        for name in REQUIRED_FIGURES:
            path = figure_dir / name
            if not path.is_file():
                failures.append(f"missing_generated_figure:{path}")
                continue
            info = _mutool_info(path)
            if expected_marker not in info:
                failures.append(f"generated_figure_hash_mismatch:{path}")
    return failures


def _paper_generated_copy_failures(
    *,
    canonical_tables: Path,
    paper_tables: Path,
    canonical_figures: Path,
    paper_figures: Path,
) -> list[str]:
    failures: list[str] = []
    for name in REQUIRED_TABLES:
        failures.extend(
            _generated_copy_pair_failures(
                canonical=canonical_tables / name,
                paper_copy=paper_tables / name,
                label="table",
            )
        )
    for name in REQUIRED_FIGURES:
        failures.extend(
            _generated_copy_pair_failures(
                canonical=canonical_figures / name,
                paper_copy=paper_figures / name,
                label="figure",
            )
        )
    return failures


def _generated_copy_pair_failures(*, canonical: Path, paper_copy: Path, label: str) -> list[str]:
    if not canonical.is_file():
        return [f"missing_canonical_generated_{label}:{canonical}"]
    if not paper_copy.is_file():
        return [f"missing_paper_generated_{label}:{paper_copy}"]
    if canonical.read_bytes() != paper_copy.read_bytes():
        return [f"paper_generated_{label}_drift:{paper_copy}:{canonical}"]
    return []


def _paper_number_macro_failures(
    *,
    summary_path: Path,
    paper_numbers_path: Path,
    lifecycle_path: Path,
    fault_path: Path,
) -> list[str]:
    failures: list[str] = []
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [f"paper_numbers_summary_unreadable:{summary_path}"]
    if not isinstance(summary, dict):
        return [f"paper_numbers_summary_invalid:{summary_path}"]
    macros, duplicates = _parse_latex_newcommands(paper_numbers_path)
    if not macros and not paper_numbers_path.is_file():
        return [f"missing_paper_numbers:{paper_numbers_path}"]
    failures.extend(f"paper_numbers_duplicate_macro:{paper_numbers_path}:{name}" for name in duplicates)
    expected: dict[str, str] = {}
    for macro, dotted_path in PAPER_NUMBER_JSON_FIELDS:
        value = _json_path_value(summary, dotted_path)
        if not isinstance(value, int):
            failures.append(f"paper_numbers_summary_field_missing:{summary_path}:{macro}:{dotted_path}")
            continue
        expected[macro] = str(value)
    for macro, dotted_path in PAPER_NUMBER_FLOAT_FIELDS:
        value = _json_path_value(summary, dotted_path)
        expected[macro] = _format_paper_number_float(value)
    lifecycle_counts, lifecycle_failures = _paper_number_lifecycle_counts(lifecycle_path)
    failures.extend(lifecycle_failures)
    expected.update(lifecycle_counts)
    fault_counts, fault_failures = _paper_number_fault_counts(fault_path)
    failures.extend(fault_failures)
    expected.update(fault_counts)
    for macro, expected_value in sorted(expected.items()):
        actual_value = macros.get(macro)
        if actual_value is None:
            failures.append(f"paper_numbers_macro_missing:{paper_numbers_path}:{macro}")
        elif actual_value != expected_value:
            failures.append(
                f"paper_numbers_macro_mismatch:{paper_numbers_path}:{macro}:"
                f"{actual_value}:{expected_value}"
            )
    return failures


def _parse_latex_newcommands(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.is_file():
        return {}, []
    text = path.read_text(encoding="utf-8", errors="ignore")
    macros: dict[str, str] = {}
    duplicates: list[str] = []
    for match in re.finditer(r"\\newcommand\{\\([A-Za-z0-9]+)\}\{([^{}]*)\}", text):
        name = match.group(1)
        if name in macros:
            duplicates.append(name)
        macros[name] = match.group(2)
    return macros, duplicates


def _json_path_value(payload: dict[str, object], dotted_path: str) -> object:
    value: object = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _format_paper_number_float(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.3f}"


def _paper_number_lifecycle_counts(path: Path) -> tuple[dict[str, str], list[str]]:
    rows, failures = _read_csv_dicts(path, "paper_numbers_lifecycle_csv")
    counts: dict[str, str] = {}
    for label, adapter in PAPER_NUMBER_LIFECYCLE_ADAPTERS:
        adapter_rows = [row for row in rows if row.get("adapter_config") == adapter]
        survived = sum(row.get("service_survived") == "true" for row in adapter_rows)
        counts[f"CVMLifecycle{label}Survived"] = str(survived)
        counts[f"CVMLifecycle{label}Total"] = str(len(adapter_rows))
    return counts, failures


def _paper_number_fault_counts(path: Path) -> tuple[dict[str, str], list[str]]:
    rows, failures = _read_csv_dicts(path, "paper_numbers_fault_csv")
    detected = sum(row.get("detected") == "true" for row in rows)
    localized = sum(row.get("correctly_localized") == "true" for row in rows)
    return (
        {
            "CVMFaultDetected": str(detected),
            "CVMFaultLocalized": str(localized),
            "CVMFaultTotal": str(len(rows)),
        },
        failures,
    )


def _generated_table_value_failures(
    *,
    tables: Path,
    summary_path: Path,
    lifecycle_path: Path,
    fault_path: Path,
) -> list[str]:
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return [f"generated_table_summary_unreadable:{summary_path}"]
    if not isinstance(summary, dict):
        return [f"generated_table_summary_invalid:{summary_path}"]
    lifecycle_counts, lifecycle_failures = _paper_number_lifecycle_counts(lifecycle_path)
    fault_counts, fault_failures = _paper_number_fault_counts(fault_path)
    failures = lifecycle_failures + fault_failures
    failures.extend(_generated_table_summary_field_failures(summary_path, summary))
    table_expectations = {
        "contract_map.tex": _expected_contract_map_rows(),
        "main_results.tex": _expected_main_results_rows(summary),
        "ablations.tex": _expected_ablations_rows(summary, lifecycle_counts),
        "fault_localization.tex": _expected_fault_localization_rows(
            lifecycle_counts,
            fault_counts,
        ),
    }
    for name, expected_rows in table_expectations.items():
        path = tables / name
        failures.extend(_table_expected_row_failures(path=path, expected_rows=expected_rows))
    return failures


def _generated_table_summary_field_failures(summary_path: Path, summary: dict[str, object]) -> list[str]:
    failures: list[str] = []
    for dotted_path in GENERATED_TABLE_JSON_FIELDS:
        if not isinstance(_json_path_value(summary, dotted_path), int):
            failures.append(f"generated_table_summary_field_missing:{summary_path}:{dotted_path}")
    return failures


def _expected_contract_map_rows() -> list[str]:
    return [
        "Command-only route & Semantic & Preserve route geometry & route-source audit",
        "Policy horizon/runtime grid & Temporal & Deterministic resampling & cadence tests",
        "Script flow/session service & Lifecycle & Idempotent late-event handling & lifecycle tests",
        "Implicit host state & Deployment & Materialized manifests & readiness checks",
        "Process exit/evidence & Evidence & Audit-valid summaries & claim gate",
    ]


def _expected_main_results_rows(summary: dict[str, object]) -> list[str]:
    return [
        _table_row(
            "CVM configured rows",
            _required_int(summary, "total_rows"),
            "--",
            _required_int(summary, "completed_runs"),
        ),
        _table_row(
            "Full-contract rollouts",
            _required_int(summary, "integration_effectiveness.full_contract_completed_runs"),
            _required_int(summary, "integration_effectiveness.full_contract_audit_valid_runs"),
            _required_int(summary, "integration_effectiveness.full_contract_completed_runs"),
        ),
        _table_row(
            "Policy-attributable behavior",
            _required_int(summary, "total_rows"),
            _required_int(summary, "failure_attribution.policy_behavior_attributable_rows"),
            "--",
        ),
        _table_row(
            "Policy-attributable failures",
            _required_int(summary, "total_rows"),
            _required_int(summary, "failure_attribution.policy_failure_attributable_rows"),
            "--",
        ),
        _table_row(
            "Integration/precondition failures",
            _required_int(summary, "total_rows"),
            _required_int(summary, "failure_attribution.integration_failure_attributable_rows"),
            "--",
        ),
        _table_row(
            "False-block observations",
            _required_int(
                summary,
                "integration_effectiveness.valid_full_contract_false_block_denominator",
            ),
            _required_int(summary, "integration_effectiveness.valid_full_contract_false_blocked_runs"),
            "--",
        ),
        _table_row(
            "Semantic ablation pairs",
            _required_int(summary, "integration_effectiveness.semantic_ablation_completed_pairs"),
            _required_int(summary, "integration_effectiveness.semantic_ablation_metric_pairs"),
            "--",
        ),
        _table_row(
            "Planned/not launched",
            _required_int(summary, "total_rows"),
            _required_int(summary, "planned_runs"),
            0,
        ),
        _table_row(
            "Blocked",
            _required_int(summary, "total_rows"),
            _required_int(summary, "blocked_runs"),
            0,
        ),
    ]


def _expected_ablations_rows(
    summary: dict[str, object],
    lifecycle_counts: dict[str, str],
) -> list[str]:
    return [
        _table_row(
            "Full-contract audit-valid rollouts",
            _required_int(summary, "integration_effectiveness.full_contract_audit_valid_runs"),
            _required_int(summary, "integration_effectiveness.full_contract_completed_runs"),
        ),
        _table_row(
            "False-blocked valid rollouts",
            _required_int(summary, "integration_effectiveness.valid_full_contract_false_blocked_runs"),
            _required_int(
                summary,
                "integration_effectiveness.valid_full_contract_false_block_denominator",
            ),
        ),
        _table_row(
            "Semantic ablation metric pairs",
            _required_int(summary, "integration_effectiveness.semantic_ablation_metric_pairs"),
            _required_int(summary, "integration_effectiveness.semantic_ablation_completed_pairs"),
        ),
        _table_row(
            "Command-proxy rows rejected",
            _required_int(
                summary,
                "integration_effectiveness.semantic_ablation_command_proxy_rejected_runs",
            ),
            _required_int(
                summary,
                "integration_effectiveness.semantic_ablation_command_proxy_completed_runs",
            ),
        ),
        _table_row(
            "Full lifecycle hardening",
            lifecycle_counts.get("CVMLifecycleFullSurvived", "0"),
            lifecycle_counts.get("CVMLifecycleFullTotal", "0"),
        ),
        _table_row(
            "Strict/pre-hardening behavior",
            lifecycle_counts.get("CVMLifecycleStrictSurvived", "0"),
            lifecycle_counts.get("CVMLifecycleStrictTotal", "0"),
        ),
    ]


def _expected_fault_localization_rows(
    lifecycle_counts: dict[str, str],
    fault_counts: dict[str, str],
) -> list[str]:
    return [
        _table_row(
            "Lifecycle hardening survived",
            lifecycle_counts.get("CVMLifecycleFullSurvived", "0"),
            lifecycle_counts.get("CVMLifecycleFullTotal", "0"),
        ),
        _table_row(
            "Pre-hardening survived",
            lifecycle_counts.get("CVMLifecycleStrictSurvived", "0"),
            lifecycle_counts.get("CVMLifecycleStrictTotal", "0"),
        ),
        _table_row(
            "Faults detected",
            fault_counts.get("CVMFaultDetected", "0"),
            fault_counts.get("CVMFaultTotal", "0"),
        ),
        _table_row(
            "Faults localized",
            fault_counts.get("CVMFaultLocalized", "0"),
            fault_counts.get("CVMFaultTotal", "0"),
        ),
    ]


def _table_expected_row_failures(*, path: Path, expected_rows: list[str]) -> list[str]:
    if not path.is_file():
        return [f"generated_table_missing_for_value_check:{path}"]
    normalized_rows = {
        _normalize_table_row(line)
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
    }
    failures: list[str] = []
    for row in expected_rows:
        if _normalize_table_row(row) not in normalized_rows:
            failures.append(f"generated_table_row_mismatch:{path}:{row}")
    return failures


def _normalize_table_row(row: str) -> str:
    row = row.strip()
    row = row.removesuffix(r"\\").strip()
    row = re.sub(r"\s*&\s*", " & ", row)
    return re.sub(r"\s+", " ", row)


def _table_row(*values: object) -> str:
    return " & ".join(str(value) for value in values)


def _required_int(payload: dict[str, object], dotted_path: str) -> int:
    value = _json_path_value(payload, dotted_path)
    return value if isinstance(value, int) else 0


def _read_csv_dicts(path: Path, label: str) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        return [], [f"{label}_missing:{path}"]
    with path.open(newline="", encoding="utf-8") as handle:
        try:
            return list(csv.DictReader(handle)), []
        except csv.Error:
            return [], [f"{label}_unreadable:{path}"]


def _frame_schema_failures(path: Path) -> list[str]:
    if not path.is_file():
        return [f"missing_frames_csv:{path}"]
    with path.open(newline="", encoding="utf-8") as handle:
        try:
            header = next(csv.reader(handle))
        except StopIteration:
            return [f"empty_frames_csv:{path}"]
    missing = [field for field in REQUIRED_FRAME_FIELDS if field not in header]
    if missing:
        return [f"frames_csv_missing_fields:{path}:{','.join(missing)}"]
    unexpected_order = list(REQUIRED_FRAME_FIELDS)
    if header[: len(unexpected_order)] != unexpected_order:
        return [f"frames_csv_field_order_mismatch:{path}"]
    return []


def _manifest_attribution_failures(manifest_dir: Path) -> list[str]:
    failures: list[str] = []
    if not manifest_dir.is_dir():
        return [f"missing_run_manifest_dir:{manifest_dir}"]
    paths = sorted(manifest_dir.glob("*.json"))
    if not paths:
        return [f"empty_run_manifest_dir:{manifest_dir}"]
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append(f"invalid_run_manifest_json:{path}")
            continue
        run_id = str(payload.get("run_id", path.stem))
        attribution = payload.get("failure_attribution")
        if not isinstance(attribution, dict):
            failures.append(f"missing_failure_attribution:{path}:{run_id}")
            continue
        failures.extend(
            _single_manifest_attribution_failures(
                payload=payload,
                attribution=attribution,
                path=path,
                run_id=run_id,
            )
        )
        failures.extend(_single_manifest_scene_failures(payload=payload, path=path, run_id=run_id))
    return failures


def _single_manifest_scene_failures(
    *,
    payload: dict[str, object],
    path: Path,
    run_id: str,
) -> list[str]:
    failures: list[str] = []
    scene = payload.get("scene")
    if not isinstance(scene, dict):
        return [f"missing_scene_metadata:{path}:{run_id}"]
    for field in REQUIRED_SCENE_FIELDS:
        if field not in scene:
            failures.append(f"missing_scene_metadata_field:{path}:{run_id}:{field}")
    scene_id = str(payload.get("scene_id", ""))
    if str(scene.get("scene_id", "")) != scene_id:
        failures.append(f"scene_metadata_id_mismatch:{path}:{run_id}")
    category = str(scene.get("category", ""))
    scenario_category = str(scene.get("scenario_category", ""))
    if not category:
        failures.append(f"scene_metadata_empty_category:{path}:{run_id}")
    if scenario_category != category:
        failures.append(f"scenario_category_mismatch:{path}:{run_id}")
    if str(payload.get("scenario_category", "")) != scenario_category:
        failures.append(f"manifest_scenario_category_mismatch:{path}:{run_id}")
    if not str(scene.get("license_gating_status", "")):
        failures.append(f"scene_metadata_missing_license_status:{path}:{run_id}")
    if not isinstance(scene.get("categories_verified"), bool):
        failures.append(f"scene_metadata_categories_verified_not_bool:{path}:{run_id}")
    return failures


def _single_manifest_attribution_failures(
    *,
    payload: dict[str, object],
    attribution: dict[str, object],
    path: Path,
    run_id: str,
) -> list[str]:
    failures: list[str] = []
    status = str(payload.get("status", ""))
    claim_valid = payload.get("claim_valid") is True
    failure_layer = str(payload.get("failure_layer", ""))
    for field in REQUIRED_ATTRIBUTION_FIELDS:
        if field not in attribution:
            failures.append(f"missing_failure_attribution_field:{path}:{run_id}:{field}")
    category = str(attribution.get("category", ""))
    if category not in ATTRIBUTION_CATEGORIES:
        failures.append(f"invalid_failure_attribution_category:{path}:{run_id}:{category}")
    interpretation = str(attribution.get("interpretation", ""))
    if interpretation not in ATTRIBUTION_INTERPRETATIONS:
        failures.append(
            f"invalid_failure_attribution_interpretation:{path}:{run_id}:{interpretation}"
        )
    expected_interpretation = _expected_failure_interpretation(
        status=status,
        claim_valid=claim_valid,
        failure_layer=failure_layer,
    )
    if expected_interpretation is not None and interpretation != expected_interpretation:
        failures.append(
            f"failure_attribution_interpretation_mismatch:{path}:{run_id}:"
            f"{status}:{interpretation}"
        )
    expected_category = (
        "policy_attributable_behavior"
        if claim_valid
        else EXPECTED_ATTRIBUTION_BY_STATUS.get(status)
    )
    if expected_category is not None and category != expected_category:
        failures.append(
            f"failure_attribution_category_mismatch:{path}:{run_id}:{status}:{category}"
        )
    if attribution.get("policy_attributable") is not claim_valid:
        failures.append(f"policy_attributable_mismatch:{path}:{run_id}")
    if attribution.get("policy_behavior_attributable") is not claim_valid:
        failures.append(f"policy_behavior_attributable_mismatch:{path}:{run_id}")
    if attribution.get("policy_failure_attributable") is not (
        claim_valid and failure_layer == "policy"
    ):
        failures.append(f"policy_failure_attributable_mismatch:{path}:{run_id}")
    if attribution.get("claim_valid_policy_benchmark") is not claim_valid:
        failures.append(f"claim_valid_policy_benchmark_mismatch:{path}:{run_id}")
    if attribution.get("integration_or_evidence_invalid") is not (not claim_valid):
        failures.append(f"integration_invalid_mismatch:{path}:{run_id}")
    if attribution.get("integration_failure_attributable") is not (
        not claim_valid and status in {"blocked", "failed"} and bool(failure_layer)
    ):
        failures.append(f"integration_failure_attributable_mismatch:{path}:{run_id}")
    attribution_failure_layer = str(attribution.get("failure_layer", ""))
    if (failure_layer == "policy" or attribution_failure_layer == "policy") and not claim_valid:
        failures.append(f"non_claim_valid_policy_failure_layer:{path}:{run_id}")
    if attribution_failure_layer != failure_layer:
        failures.append(f"failure_attribution_layer_mismatch:{path}:{run_id}")
    if str(attribution.get("failure_code", "")) != str(payload.get("failure_code", "")):
        failures.append(f"failure_attribution_code_mismatch:{path}:{run_id}")
    rule = str(attribution.get("rule", ""))
    required_rule_terms = (
        "policy-attributable",
        "policy failure",
        "semantic",
        "temporal",
        "lifecycle",
        "deployment",
        "evidence",
    )
    if not all(term in rule for term in required_rule_terms):
        failures.append(f"failure_attribution_rule_missing:{path}:{run_id}")
    return failures


def _expected_failure_interpretation(
    *,
    status: str,
    claim_valid: bool,
    failure_layer: str,
) -> str | None:
    if claim_valid:
        return "policy_behavior_allowed"
    if status == "blocked":
        return "integration_precondition_blocker_not_policy_failure"
    if status == "failed":
        return "integration_runtime_or_evidence_failure_not_policy_failure"
    if status == "completed" and failure_layer:
        return "controlled_contract_diagnostic_not_policy_failure"
    if status == "completed":
        return "completed_diagnostic_pending_evidence_gate_not_policy_failure"
    if status == "planned":
        return "planned_not_launched_not_policy_failure"
    return None


def _release_hygiene_failures(*, repo_root: Path, canonical_paper: Path) -> list[str]:
    root = repo_root.resolve()
    canonical = (root / canonical_paper).resolve() if not canonical_paper.is_absolute() else canonical_paper.resolve()
    failures = _duplicate_manuscript_pdf_failures(root=root, canonical_paper=canonical)
    failures.extend(_package_metadata_failures(repo_root=root))
    failures.extend(_ci_workflow_failures(repo_root=root))
    failures.extend(_cli_documentation_failures(repo_root=root))
    for path in _iter_public_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel_path = path.relative_to(root)
        for label, pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(text):
                failures.append(f"public_hygiene:{label}:{rel_path}")
        failures.extend(_public_local_reference_failures(path=path, text=text, root=root))
        failures.extend(_public_image_alt_failures(path=path, text=text, root=root))
    for archive_path in _iter_public_scan_archives(root):
        failures.extend(_archive_hygiene_failures(archive_path, root=root))
    return failures


def _ci_workflow_failures(*, repo_root: Path) -> list[str]:
    path = repo_root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return ["ci_workflow_missing:.github/workflows/ci.yml"]
    if not path.is_file():
        return ["ci_workflow_source_invalid:.github/workflows/ci.yml"]
    text = path.read_text(encoding="utf-8", errors="ignore")
    failures: list[str] = []
    for token in REQUIRED_CI_WORKFLOW_TOKENS:
        if token not in text:
            failures.append(f"ci_workflow_gate_missing:.github/workflows/ci.yml:{token}")
    if "permissions:\n  contents: read" not in text:
        failures.append("ci_workflow_permissions_not_minimal:.github/workflows/ci.yml")
    if "pull_request:" not in text or 'branches: ["main"]' not in text:
        failures.append("ci_workflow_trigger_missing:.github/workflows/ci.yml")
    return failures


def _package_metadata_failures(*, repo_root: Path) -> list[str]:
    path = repo_root / "pyproject.toml"
    if not path.exists():
        return []
    if not path.is_file():
        return ["package_metadata_source_invalid:pyproject.toml"]
    text = path.read_text(encoding="utf-8", errors="ignore")
    project = _toml_section_text(text, "project")
    urls = _toml_section_text(text, "project.urls")
    failures: list[str] = []
    if not project.strip():
        return ["package_metadata_project_section_missing:pyproject.toml"]
    if "authors" not in project or "Alba Maria Tellez Fernandez" not in project:
        failures.append("package_metadata_author_missing:pyproject.toml")
    if 'readme = "README.md"' not in project:
        failures.append("package_metadata_readme_missing:pyproject.toml")
    if 'license = "BSD-3-Clause"' not in project:
        failures.append("package_metadata_license_missing:pyproject.toml")
    for keyword in REQUIRED_PROJECT_KEYWORDS:
        if f'"{keyword}"' not in project:
            failures.append(f"package_metadata_keyword_missing:pyproject.toml:{keyword}")
    for classifier in REQUIRED_PROJECT_CLASSIFIERS:
        if f'"{classifier}"' not in project:
            failures.append(f"package_metadata_classifier_missing:pyproject.toml:{classifier}")
    if not urls.strip():
        failures.append("package_metadata_urls_missing:pyproject.toml")
    else:
        for key in REQUIRED_PROJECT_URLS:
            if re.search(rf"(?m)^\s*{re.escape(key)}\s*=", urls) is None:
                failures.append(f"package_metadata_url_missing:pyproject.toml:{key}")
    return failures


def _toml_section_text(text: str, section: str) -> str:
    match = re.search(
        rf"(?ms)^\[{re.escape(section)}\]\s*$\n?(.*?)(?=^\[|\Z)",
        text,
    )
    return "" if match is None else match.group(1)


def _cli_documentation_failures(*, repo_root: Path) -> list[str]:
    root = repo_root.resolve()
    cli_doc = root / "docs" / "cli.md"
    pyproject = root / "pyproject.toml"
    makefile = root / "Makefile"
    source_paths = (cli_doc, pyproject, makefile)
    if not any(path.exists() for path in source_paths):
        return []
    failures: list[str] = []
    if not cli_doc.is_file():
        return ["cli_doc_missing:docs/cli.md"]
    text = cli_doc.read_text(encoding="utf-8", errors="ignore")
    if not pyproject.is_file():
        failures.append("cli_doc_source_missing:pyproject.toml")
    else:
        for command in _project_script_names(pyproject):
            if f"`{command}`" not in text:
                failures.append(f"cli_doc_missing_console_script:docs/cli.md:{command}")
    if not makefile.is_file():
        failures.append("cli_doc_source_missing:Makefile")
    else:
        for target in _make_phony_targets(makefile):
            if f"`make {target}`" not in text:
                failures.append(f"cli_doc_missing_make_target:docs/cli.md:{target}")
    return failures


def _project_script_names(path: Path) -> list[str]:
    names: list[str] = []
    in_scripts = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts and stripped.startswith("[") and stripped.endswith("]"):
            break
        if not in_scripts:
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*=", stripped)
        if match is not None:
            names.append(match.group(1))
    return sorted(dict.fromkeys(names))


def _make_phony_targets(path: Path) -> list[str]:
    targets: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith(".PHONY:"):
            continue
        targets.extend(token for token in line.split(":", 1)[1].split() if token)
    return list(dict.fromkeys(targets))


def _duplicate_manuscript_pdf_failures(*, root: Path, canonical_paper: Path) -> list[str]:
    failures: list[str] = []
    for name in DUPLICATE_MANUSCRIPT_PDFS:
        path = (root / name).resolve()
        if path.is_file() and path != canonical_paper:
            failures.append(f"duplicate_manuscript_pdf:{path.relative_to(root)}")
    return failures


def _iter_public_scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for item in PUBLIC_SCAN_PATHS:
        path = root / item
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix.lower() not in TEXT_SKIP_SUFFIXES:
                files.append(path)
            continue
        files.extend(
            candidate
            for candidate in sorted(path.rglob("*"))
            if candidate.is_file()
            and candidate.suffix.lower() not in TEXT_SKIP_SUFFIXES
            and not _is_raw_local_execution_artifact(candidate, root=root)
        )
    return sorted(set(files))


def _iter_public_scan_archives(root: Path) -> list[Path]:
    archives: list[Path] = []
    for item in PUBLIC_SCAN_PATHS:
        path = root / item
        if not path.exists():
            continue
        if path.is_file():
            if path.name.endswith(".tar.gz"):
                archives.append(path)
            continue
        archives.extend(
            candidate
            for candidate in sorted(path.rglob("*.tar.gz"))
            if not _is_raw_local_execution_artifact(candidate, root=root)
        )
    return sorted(set(archives))


def _is_raw_local_execution_artifact(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    parts = relative.parts
    if any(part in PUBLIC_SCAN_SKIP_NAMES or part.endswith(".egg-info") for part in parts):
        return True
    return any(_parts_start_with(parts, skipped) for skipped in PUBLIC_SCAN_SKIP_PARTS)


def _parts_start_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(parts) >= len(prefix) and parts[: len(prefix)] == prefix


def _public_local_reference_failures(*, path: Path, text: str, root: Path) -> list[str]:
    if path.suffix.lower() not in {".md", ".html", ".htm"}:
        return []
    failures: list[str] = []
    rel_path = path.relative_to(root)
    for target in _public_local_reference_targets(text):
        resolved = _resolve_public_local_reference(path=path, target=target, root=root)
        if resolved is None:
            continue
        target_path, cleaned_target = resolved
        try:
            target_path.relative_to(root)
        except ValueError:
            failures.append(f"public_local_reference_outside_root:{rel_path}:{cleaned_target}")
            continue
        if not target_path.exists():
            failures.append(f"public_local_reference_missing:{rel_path}:{cleaned_target}")
    return failures


def _public_local_reference_targets(text: str) -> list[str]:
    targets: list[str] = []
    targets.extend(match.group(1) for match in MARKDOWN_LINK_RE.finditer(text))
    targets.extend(match.group(1) for match in HTML_LOCAL_REF_RE.finditer(text))
    return targets


def _resolve_public_local_reference(*, path: Path, target: str, root: Path) -> tuple[Path, str] | None:
    cleaned = target.strip().strip("<>")
    if not cleaned or cleaned.startswith("#"):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", cleaned) or cleaned.startswith("//"):
        return None
    cleaned = cleaned.split("#", 1)[0].split("?", 1)[0]
    if not cleaned:
        return None
    cleaned = unquote(cleaned)
    target_path = root / cleaned.lstrip("/") if cleaned.startswith("/") else path.parent / cleaned
    return target_path.resolve(), cleaned


def _public_image_alt_failures(*, path: Path, text: str, root: Path) -> list[str]:
    if path.suffix.lower() not in {".md", ".html", ".htm"}:
        return []
    rel_path = path.relative_to(root)
    failures: list[str] = []
    for alt_text, target in MARKDOWN_IMAGE_RE.findall(text):
        if not alt_text.strip():
            failures.append(f"public_image_alt_missing:{rel_path}:{target.strip() or '<empty-target>'}")
    for tag in HTML_IMAGE_TAG_RE.findall(text):
        alt_match = HTML_ALT_ATTR_RE.search(tag)
        if alt_match is None or not alt_match.group(2).strip():
            src_match = re.search(r"\bsrc\s*=\s*(['\"])(.*?)\1", tag, re.IGNORECASE)
            src = src_match.group(2).strip() if src_match else "<missing-src>"
            failures.append(f"public_image_alt_missing:{rel_path}:{src}")
    return failures


def _archive_hygiene_failures(path: Path, *, root: Path) -> list[str]:
    failures: list[str] = []
    rel_path = path.relative_to(root)
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or Path(member.name).suffix.lower() not in ARCHIVE_TEXT_SUFFIXES:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                try:
                    text = handle.read().decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for label, pattern in FORBIDDEN_TEXT_PATTERNS:
                    if pattern.search(text):
                        failures.append(f"public_hygiene_archive:{label}:{rel_path}:{member.name}")
    except tarfile.TarError:
        failures.append(f"invalid_public_archive:{rel_path}")
    return failures


def _summary_int(summary: object, key: str) -> int:
    if not isinstance(summary, dict):
        return 0
    value = summary.get(key)
    return int(value) if isinstance(value, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
