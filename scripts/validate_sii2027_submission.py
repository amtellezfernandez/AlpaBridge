from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

PLACEHOLDERS = ("TODO", "TBD", "FIXME", "RESULTS_PENDING", "[N]", "[M]")
EXPECTED_TITLE = (
    "WOD2Sim: Contract-Based System Integration of Dataset-Trained Driving Policies "
    "into Distributed Closed-Loop Simulation"
)
EXPECTED_AUTHOR = "Alba Maria Tellez Fernandez"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the SII 2027 paper artifact.")
    parser.add_argument("--paper", default=Path("wod2sim.pdf"), type=Path)
    parser.add_argument("--source", default=Path("paper/sii2027"), type=Path)
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
    else:
        failures.append("missing_latex_log")

    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("sii2027 submission validation passed")
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


if __name__ == "__main__":
    raise SystemExit(main())
