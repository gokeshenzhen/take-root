from __future__ import annotations

from pathlib import Path

import pytest

from take_root.errors import ArtifactError
from take_root.phases import format_boot_message, validate_artifact


def test_format_boot_message_basic() -> None:
    message = format_boot_message(
        "demo",
        project_root="/tmp/p",
        reference_files=["/tmp/a.md"],
        flag=True,
        nothing=None,
    )
    assert message.startswith("[take-root harness boot]")
    assert "flag: true" in message
    assert "nothing: null" in message


def test_format_boot_message_size_limit() -> None:
    with pytest.raises(ArtifactError):
        format_boot_message("demo", text="x" * (33 * 1024))


def test_validate_artifact_success(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("---\na: 1\nb: 2\n---\nbody\n", encoding="utf-8")
    meta = validate_artifact(path, ["a", "b"])
    assert meta["a"] == 1


def test_validate_artifact_missing_required(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("---\na: 1\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ArtifactError):
        validate_artifact(path, ["a", "b"])
