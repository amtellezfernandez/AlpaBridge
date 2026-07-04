from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _detect_source_repo_root() -> Path | None:
    src_root = PACKAGE_ROOT.parent
    repo_root = src_root.parent
    if src_root.name != "src":
        return None
    if not (repo_root / "pyproject.toml").is_file():
        return None
    return repo_root


SOURCE_REPO_ROOT = _detect_source_repo_root()
WORKSPACE_ROOT = SOURCE_REPO_ROOT or Path.cwd()


def package_path(*parts: str) -> Path:
    return PACKAGE_ROOT.joinpath(*parts)


def workspace_path(*parts: str) -> Path:
    return WORKSPACE_ROOT.joinpath(*parts)


def repo_path(*parts: str) -> Path | None:
    if SOURCE_REPO_ROOT is None:
        return None
    return SOURCE_REPO_ROOT.joinpath(*parts)
