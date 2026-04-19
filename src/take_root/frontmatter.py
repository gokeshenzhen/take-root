from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class FrontmatterError(ValueError):
    """Raised when frontmatter parsing fails."""


@dataclass(frozen=True)
class ParsedFrontmatter:
    metadata: dict[str, Any]
    body: str


def parse_frontmatter(text: str) -> ParsedFrontmatter:
    """Parse markdown text with YAML frontmatter."""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise FrontmatterError("Missing YAML frontmatter start delimiter")
    end_marker = normalized.find("\n---\n", 4)
    if end_marker == -1:
        raise FrontmatterError("Missing YAML frontmatter end delimiter")
    raw_meta = normalized[4:end_marker]
    body = normalized[end_marker + 5 :]
    loaded = yaml.safe_load(raw_meta) if raw_meta.strip() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise FrontmatterError("Frontmatter must be a mapping")
    return ParsedFrontmatter(metadata=dict(loaded), body=body)


def serialize_frontmatter(metadata: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body as markdown."""
    dumped = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{dumped}\n---\n{body}"


def read_frontmatter_file(path: Path) -> ParsedFrontmatter:
    """Read and parse a frontmatter markdown file."""
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def write_frontmatter_file(path: Path, metadata: dict[str, Any], body: str) -> None:
    """Write frontmatter markdown atomically."""
    payload = serialize_frontmatter(metadata, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
