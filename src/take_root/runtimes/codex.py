from __future__ import annotations

import json
import subprocess
from pathlib import Path

from take_root.errors import ConfigError
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult

CODEX_REASONING_ALLOWED = {"minimal", "low", "medium", "high"}


def _as_toml_string(value: str) -> str:
    # JSON string literal is TOML-compatible for basic strings.
    return json.dumps(value)


class CodexRuntime(BaseRuntime):
    @classmethod
    def check_available(cls) -> None:
        result = subprocess.run(
            ["codex", "--version"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise ConfigError("Codex CLI not available: run `codex --version` to verify install")

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 3600,
    ) -> RuntimeCallResult:
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-m",
            self.persona.model,
            "-c",
            f"developer_instructions={_as_toml_string(self.persona.system_prompt)}",
        ]
        if self.persona.reasoning:
            effort = self.persona.reasoning.lower()
            if effort in CODEX_REASONING_ALLOWED:
                cmd.extend(
                    [
                        "-c",
                        f"model_reasoning_effort={_as_toml_string(effort)}",
                    ]
                )
        cmd.append(boot_message)
        return self._run_noninteractive_with_policy(cmd, cwd, timeout_sec)

    def call_interactive(
        self,
        boot_message: str,
        cwd: Path,
    ) -> RuntimeCallResult:
        del boot_message, cwd
        raise NotImplementedError("CodexRuntime does not support interactive mode in take-root v1")
