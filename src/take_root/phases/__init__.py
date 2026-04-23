from __future__ import annotations

import json
import logging
import re
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
    _validate_artifact_structure(path, metadata, parsed.body)
    return metadata


def _validate_artifact_structure(path: Path, metadata: dict[str, Any], body: str) -> None:
    artifact = metadata.get("artifact")
    if artifact == "robin_review":
        _validate_robin_review(path, metadata, body)
        return
    if artifact == "neo_review":
        _validate_neo_review(path, metadata, body)
        return
    if artifact == "final_plan":
        _validate_final_plan(path, body)


def _validate_robin_review(path: Path, metadata: dict[str, Any], body: str) -> None:
    round_num = _require_int_key(path, metadata, "round")
    _require_int_key(path, metadata, "remaining_concerns")
    _require_heading(path, body, r"^# Robin — Round \d+ Review$")
    if round_num > 1:
        _require_heading(path, body, r"^## 1\. 对 Neo 的回应")
    _require_heading(path, body, r"^## 2\. 新发现 / 我的关切$")
    _require_heading(path, body, r"^## 3\. 收敛评估$")


def _validate_neo_review(path: Path, metadata: dict[str, Any], body: str) -> None:
    round_num = _require_int_key(path, metadata, "round")
    _require_int_key(path, metadata, "open_attacks")
    _require_heading(path, body, r"^# Neo — Round \d+ Adversarial Review$")
    if round_num > 1:
        _require_heading(path, body, r"^## 1\. 对 Robin 上轮回应的处置")
    _require_heading(path, body, r"^## 2\. 新攻击点$")
    _require_heading(path, body, r"^## 3\. 收敛评估$")


def _validate_final_plan(path: Path, body: str) -> None:
    headings = (
        r"^# 最终方案：.+$",
        r"^## 1\. 目标$",
        r"^## 2\. 非目标$",
        r"^## 3\. 背景与约束$",
        r"^## 4\. 设计概览$",
        r"^## 5\. 关键决策$",
        r"^## 6\. 实施步骤$",
        r"^## 7\. 验收标准$",
        r"^## 8\. 已知风险与未决问题$",
    )
    for pattern in headings:
        _require_heading(path, body, pattern)


def _require_int_key(path: Path, metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    if not isinstance(value, int):
        raise ArtifactError(f"Artifact key {key!r} must be an integer: {path}")
    return value


def _require_heading(path: Path, body: str, pattern: str) -> None:
    if re.search(pattern, body, re.MULTILINE) is None:
        raise ArtifactError(f"Artifact missing required section / heading {pattern!r}: {path}")
