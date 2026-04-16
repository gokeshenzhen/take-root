from __future__ import annotations

from pathlib import Path

from take_root.frontmatter import ParsedFrontmatter, read_frontmatter_file
from take_root.state import ensure_take_root_dirs, take_root_dir


def ensure_layout(project_root: Path) -> None:
    ensure_take_root_dirs(project_root)


def phase_dir(project_root: Path, phase: str) -> Path:
    return take_root_dir(project_root) / phase


def artifact_path(project_root: Path, phase: str, filename: str) -> Path:
    return phase_dir(project_root, phase) / filename


def run_summary_path(project_root: Path) -> Path:
    return take_root_dir(project_root) / "run_summary.md"


def list_artifact_files(project_root: Path, phase: str | None = None) -> list[Path]:
    root = take_root_dir(project_root)
    if phase is not None:
        return sorted((root / phase).glob("*.md"))
    return sorted(root.rglob("*.md"))


def load_artifact(path: Path) -> ParsedFrontmatter:
    return read_frontmatter_file(path)
