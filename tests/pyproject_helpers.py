from __future__ import annotations

from pathlib import Path
import re


_SECTION_RE = re.compile(r"^\[(?P<section>.+)]$")
_STRING_ASSIGNMENT_RE = re.compile(r'^(?P<key>[A-Za-z0-9_.-]+)\s*=\s*"(?P<value>.*)"\s*$')


def load_string_tables(path: str | Path) -> dict[str, dict[str, str]]:
    """Load simple string-valued tables from pyproject.toml for tests.

    The project supports Python 3.10, so tests should not depend on the Python
    3.11-only stdlib `tomllib`. This parser intentionally supports only the
    string assignment tables used by the boundary and entrypoint tests.
    """

    tables: dict[str, dict[str, str]] = {}
    current_section: str | None = None
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("section")
            tables.setdefault(current_section, {})
            continue
        assignment_match = _STRING_ASSIGNMENT_RE.match(line)
        if current_section is not None and assignment_match:
            tables[current_section][assignment_match.group("key")] = assignment_match.group("value")
    return tables
