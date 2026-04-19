from __future__ import annotations

import os
from pathlib import Path

from take_root.config import TakeRootConfig, resolve_persona_runtime_config
from take_root.errors import ConfigError
from take_root.persona import Persona
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult, RuntimeConfig, RuntimePolicy
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime

_RUNTIME_OVERRIDE_ENV = "TAKE_ROOT_RUNTIME_OVERRIDE"


def runtime_for(
    persona: Persona,
    project_root: Path,
    config: TakeRootConfig,
) -> BaseRuntime:
    """Build the runtime for a persona, honoring TAKE_ROOT_RUNTIME_OVERRIDE=fake."""
    resolved_config = resolve_persona_runtime_config(config, persona.name)
    override = os.getenv(_RUNTIME_OVERRIDE_ENV)
    if override == "fake":
        from take_root.runtimes.fake import FakeRuntime

        return FakeRuntime(persona, project_root, resolved_config=resolved_config)
    if resolved_config.runtime_name == "claude":
        return ClaudeRuntime(persona, project_root, resolved_config=resolved_config)
    if resolved_config.runtime_name == "codex":
        return CodexRuntime(persona, project_root, resolved_config=resolved_config)
    raise ConfigError(f"Unsupported runtime: {resolved_config.runtime_name}")


def check_runtime_available(runtime_name: str) -> None:
    """Dispatch to runtime-specific availability checks unless fake override is enabled."""
    if os.getenv(_RUNTIME_OVERRIDE_ENV) == "fake":
        return
    if runtime_name == "claude":
        ClaudeRuntime.check_available()
        return
    if runtime_name == "codex":
        CodexRuntime.check_available()
        return
    raise ConfigError(f"Unsupported runtime: {runtime_name}")


__all__ = [
    "BaseRuntime",
    "ClaudeRuntime",
    "CodexRuntime",
    "RuntimeCallResult",
    "RuntimeConfig",
    "RuntimePolicy",
    "check_runtime_available",
    "runtime_for",
]
