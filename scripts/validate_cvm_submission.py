from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Pattern

PLACEHOLDERS = ("TODO", "TBD", "FIXME", "RESULTS_PENDING", "[N]", "[M]")
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
    parser = argparse.ArgumentParser(description="Validate the WOD2Sim paper artifact.")
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
