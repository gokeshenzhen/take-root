from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from take_root.errors import ConfigError
from take_root.frontmatter import FrontmatterError, read_frontmatter_file

LOGGER = logging.getLogger(__name__)

VALID_RUNTIMES = {"claude", "codex"}


@dataclass(frozen=True)
class Persona:
    name: str
    role: str
    runtime: str
    interactive: bool
    output_artifacts: list[str]
    system_prompt: str
    source_path: Path
    raw_frontmatter: dict[str, Any]


def find_harness_root(start: Path | None = None) -> Path:
    """Find harness repo root by walking parents and locating personas/."""
    here = start if start is not None else Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "personas").is_dir():
            return parent
    raise ConfigError("Cannot locate harness root with personas directory")


def _normalize_output_artifacts(meta: dict[str, Any]) -> list[str]:
    artifacts = meta.get("output_artifacts")
    if artifacts is None and "output_artifact" in meta:
        # SPEC-GAP: jeff.md currently uses `output_artifact` singular.
        single = meta["output_artifact"]
        if isinstance(single, str):
            return [single]
        raise ConfigError("output_artifact must be a string when provided")
    if not isinstance(artifacts, list) or not artifacts:
        raise ConfigError("output_artifacts must be a non-empty list")
    values: list[str] = []
    for item in artifacts:
        if not isinstance(item, str):
            raise ConfigError("output_artifacts must contain strings")
        values.append(item)
    return values


def _validate_required_keys(meta: dict[str, Any]) -> None:
    required = ["name", "role", "runtime", "interactive"]
    missing = [key for key in required if key not in meta]
    if missing:
        raise ConfigError(f"Missing persona frontmatter keys: {', '.join(missing)}")


def _to_persona(path: Path) -> Persona:
    try:
        parsed = read_frontmatter_file(path)
    except FrontmatterError as exc:
        raise ConfigError(f"Invalid persona frontmatter: {path}") from exc
    meta = parsed.metadata
    _validate_required_keys(meta)
    name = meta["name"]
    role = meta["role"]
    runtime = meta["runtime"]
    interactive = meta["interactive"]
    if not isinstance(name, str) or not name:
        raise ConfigError(f"Invalid persona name in {path}")
    if not isinstance(role, str) or not role:
        raise ConfigError(f"Invalid persona role in {path}")
    if not isinstance(runtime, str) or runtime not in VALID_RUNTIMES:
        raise ConfigError(f"Invalid runtime in {path}: {runtime!r}")
    if not isinstance(interactive, bool):
        raise ConfigError(f"Invalid interactive flag in {path}")
    output_artifacts = _normalize_output_artifacts(meta)
    return Persona(
        name=name,
        role=role,
        runtime=runtime,
        interactive=interactive,
        output_artifacts=output_artifacts,
        system_prompt=parsed.body.lstrip("\n"),
        source_path=path,
        raw_frontmatter=meta,
    )


def load_persona(name: str, project_root: Path, harness_root: Path | None = None) -> Persona:
    """
    Load persona with per-project override priority.

    Resolution order:
      1. <project_root>/.take_root/personas/<name>.md
      2. <harness_root>/personas/<name>.md
    """
    root = harness_root if harness_root is not None else find_harness_root()
    override = project_root / ".take_root" / "personas" / f"{name}.md"
    default = root / "personas" / f"{name}.md"
    source = override if override.exists() else default
    if not source.exists():
        raise ConfigError(f"Persona file not found: {source}")
    LOGGER.debug("load_persona(%s): using %s", name, source)
    persona = _to_persona(source)
    if persona.name != name:
        raise ConfigError(
            f"Persona name mismatch in {source}: expected {name!r}, found {persona.name!r}"
        )
    return persona
