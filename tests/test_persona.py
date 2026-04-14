from __future__ import annotations

from pathlib import Path

import pytest

from take_root.errors import ConfigError
from take_root.persona import load_persona


def _write_persona(path: Path, *, output_key: str = "output_artifacts") -> None:
    content = (
        "---\n"
        "name: demo\n"
        "role: test role\n"
        "runtime: codex\n"
        "model: gpt-5.4\n"
        "reasoning: high\n"
        "interactive: false\n"
    )
    if output_key == "output_artifacts":
        content += "output_artifacts:\n  - .take_root/plan/demo.md\n"
    else:
        content += "output_artifact: .take_root/plan/demo.md\n"
    content += "---\n# prompt\nhello\n"
    path.write_text(content, encoding="utf-8")


def test_load_persona_default_and_override(tmp_path: Path) -> None:
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    default_path = harness_root / "personas" / "demo.md"
    override_path = project_root / ".take_root" / "personas" / "demo.md"
    default_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.parent.mkdir(parents=True, exist_ok=True)
    _write_persona(default_path)
    _write_persona(override_path)
    override_path.write_text(
        override_path.read_text(encoding="utf-8").replace("test role", "override role"),
        encoding="utf-8",
    )
    persona = load_persona("demo", project_root, harness_root=harness_root)
    assert persona.role == "override role"
    assert persona.source_path == override_path


def test_load_persona_supports_singular_output_key(tmp_path: Path) -> None:
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    path = harness_root / "personas" / "demo.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_persona(path, output_key="output_artifact")
    persona = load_persona("demo", project_root, harness_root=harness_root)
    assert persona.output_artifacts == [".take_root/plan/demo.md"]


def test_load_persona_missing_key_raises(tmp_path: Path) -> None:
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    path = harness_root / "personas" / "demo.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nname: demo\nruntime: codex\nmodel: gpt-5.4\ninteractive: false\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_persona("demo", project_root, harness_root=harness_root)
