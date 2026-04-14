from __future__ import annotations

import subprocess
import time
from pathlib import Path

from take_root.errors import ConfigError, RuntimeCallError
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult

CLAUDE_REASONING_MAP = {
    "minimal": "low",  # SPEC-GAP: Claude CLI offers low/medium/high/max only.
    "low": "low",
    "medium": "medium",
    "high": "high",
}


class ClaudeRuntime(BaseRuntime):
    @classmethod
    def check_available(cls) -> None:
        result = subprocess.run(
            ["claude", "--version"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise ConfigError("Claude CLI not available: run `claude --version` to verify install")

    def _build_common_args(self) -> list[str]:
        args = [
            "--append-system-prompt",
            self.persona.system_prompt,
            "--model",
            self.persona.model,
        ]
        if self.persona.reasoning:
            effort = CLAUDE_REASONING_MAP.get(self.persona.reasoning.lower())
            if effort:
                args.extend(["--effort", effort])
        return args

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 3600,
    ) -> RuntimeCallResult:
        cmd = ["claude", "-p", boot_message, *self._build_common_args()]
        return self._run_noninteractive_with_policy(cmd, cwd, timeout_sec)

    def call_interactive(
        self,
        boot_message: str,
        cwd: Path,
    ) -> RuntimeCallResult:
        started = time.monotonic()
        cmd = ["claude", boot_message, *self._build_common_args()]
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            check=False,
        )
        duration = time.monotonic() - started
        if completed.returncode != 0:
            raise RuntimeCallError(f"interactive Claude exited with code {completed.returncode}")
        return RuntimeCallResult(
            exit_code=completed.returncode,
            stdout="",
            stderr="",
            duration_sec=duration,
        )
