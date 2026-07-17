from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Pattern

PLACEHOLDERS = ("TODO", "TBD", "FIXME", "RESULTS_PENDING", "[N]", "[M]")
ABSTRACT_MIN_WORDS = 160
ABSTRACT_MAX_WORDS = 210
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
EXPECTED_TITLE = (
    "WOD2Sim: Contract-Based System Integration of Dataset-Trained Driving Policies "
    "into Distributed Closed-Loop Simulation"
)
EXPECTED_AUTHOR = "Alba Maria Tellez Fernandez"
PUBLIC_SCAN_PATHS = (
    "README.md",
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
    ("weak_adapter_artifact_label", re.compile(r"\badapter\s+and\s+evaluation\s+artifact\b", re.IGNORECASE)),
    ("weak_artifact_scaffold_label", re.compile(r"\bartifact\s+scaffold\b", re.IGNORECASE)),
    (
        "venue_coupled_artifact_name",
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
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--max-pages", default=6, type=int)
    parser.add_argument("--allow-eight-pages", action="store_true")
    args = parser.parse_args()

    failures: list[str] = []
    if not args.paper.is_file():
        failures.append(f"missing_pdf:{args.paper}")
    else:
        size = args.paper.stat().st_size
        if size > 6 * 1024 * 1024:
            failures.append(f"pdf_too_large:{size}")
        info = _mutool_info(args.paper)
        pages = _extract_pages(info)
        if pages is None:
            failures.append("page_count_unavailable")
        else:
            max_pages = 8 if args.allow_eight_pages else args.max_pages
            if pages < 4 or pages > max_pages:
                failures.append(f"page_count_out_of_range:{pages}")
        if "[ 0 0 595" not in info and "[0 0 595" not in info:
            failures.append("page_size_not_verified_as_a4")
        if not re.search(r"/Title(?:<[^>]+>|\([^)]+\))", info):
            failures.append("pdf_title_metadata_missing")
        if not re.search(r"/Author(?:<[^>]+>|\([^)]+\))", info):
            failures.append("pdf_author_metadata_missing")

    main_tex = args.source / "main.tex"
    source_text = main_tex.read_text(encoding="utf-8", errors="ignore") if main_tex.is_file() else ""
    if EXPECTED_TITLE not in source_text:
        failures.append("source_title_mismatch")
    if EXPECTED_AUTHOR not in source_text:
        failures.append("source_author_missing")
    if "Independent Researcher" not in source_text:
        failures.append("source_affiliation_missing")
    failures.extend(_source_text_failures(source_text=source_text, path=main_tex))

    for path in sorted(args.source.rglob("*.tex")) + sorted(args.source.rglob("*.bib")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in PLACEHOLDERS:
            if token in text:
                failures.append(f"placeholder:{path}:{token}")
        if re.search(r"/home/[A-Za-z0-9_.-]+", text):
            failures.append(f"private_path:{path}")

    log = args.source / "main.log"
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="ignore")
        for pattern in (
            "Undefined control sequence",
            "Citation `",
            "Reference `",
            "multiply defined",
        ):
            if pattern in text:
                failures.append(f"latex_log_warning:{pattern}")

    data_hash = _load_summary_data_hash(args.results / "summary.json")
    if data_hash is None:
        failures.append("missing_or_invalid_summary_data_hash")
    else:
        failures.extend(
            _generated_artifact_failures(
                data_hash=data_hash,
                table_dirs=(args.tables, args.source / "generated"),
                figure_dirs=(args.figures, args.source / "figures"),
            )
        )
    failures.extend(_frame_schema_failures(args.results / "frames.csv"))
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


def _extract_pages(info: str) -> int | None:
    match = re.search(r"Pages:\s+(\d+)", info)
    return None if match is None else int(match.group(1))


def _load_summary_data_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    data_hash = payload.get("data_hash")
    return data_hash if isinstance(data_hash, str) and data_hash else None


def _source_text_failures(*, source_text: str, path: Path) -> list[str]:
    failures: list[str] = []
    abstract_words = _abstract_word_count(source_text)
    if abstract_words is None:
        failures.append(f"missing_abstract:{path}")
    elif abstract_words < ABSTRACT_MIN_WORDS or abstract_words > ABSTRACT_MAX_WORDS:
        failures.append(f"abstract_word_count_out_of_range:{path}:{abstract_words}")
    if re.search(r"pdfsubject\s*=\s*\{[^}]*\bdraft\b", source_text, re.IGNORECASE):
        failures.append(f"source_pdfsubject_marked_draft:{path}")
    return failures


def _abstract_word_count(source_text: str) -> int | None:
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", source_text, re.DOTALL)
    if match is None:
        return None
    abstract = re.sub(r"%.*", "", match.group(1))
    abstract = abstract.replace(r"\_", "_")
    abstract = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{\}", " number ", abstract)
    abstract = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r" \1 ", abstract)
    abstract = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", abstract)
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", abstract))


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
    for path in _iter_public_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel_path = path.relative_to(root)
        for label, pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(text):
                failures.append(f"public_hygiene:{label}:{rel_path}")
    for archive_path in _iter_public_scan_archives(root):
        failures.extend(_archive_hygiene_failures(archive_path, root=root))
    return failures


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


if __name__ == "__main__":
    raise SystemExit(main())
