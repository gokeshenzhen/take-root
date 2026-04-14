from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from take_root.errors import ArtifactError
from take_root.frontmatter import FrontmatterError, read_frontmatter_file

LOGGER = logging.getLogger(__name__)

BOOT_WARN_BYTES = 8 * 1024
BOOT_ABORT_BYTES = 32 * 1024


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        if any(isinstance(item, str) and " " in item for item in value):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return _format_scalar(value)


def format_boot_message(persona_name: str, **kwargs: Any) -> str:
    lines = ["[take-root harness boot]"]
    for key, value in kwargs.items():
        lines.append(f"{key}: {_format_value(value)}")
    message = "\n".join(lines)
    size = len(message.encode("utf-8"))
    if size > BOOT_ABORT_BYTES:
        raise ArtifactError(
            f"Boot message for {persona_name} is too large: {size} bytes (> {BOOT_ABORT_BYTES})"
        )
    if size > BOOT_WARN_BYTES:
        LOGGER.warning("Boot message for %s is large: %d bytes", persona_name, size)
    return message


def validate_artifact(path: Path, required_keys: list[str]) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise ArtifactError(f"Expected artifact not found or empty: {path}")
    try:
        parsed = read_frontmatter_file(path)
    except FrontmatterError as exc:
        raise ArtifactError(f"Invalid frontmatter in artifact: {path}") from exc
    metadata = parsed.metadata
    missing = [key for key in required_keys if key not in metadata]
    if missing:
        raise ArtifactError(f"Artifact missing required keys {missing}: {path}")
    return metadata
