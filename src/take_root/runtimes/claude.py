from __future__ import annotations

import subprocess
import time
from pathlib import Path

from take_root.errors import ConfigError, RuntimeCallError
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult, RuntimePolicy


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

    def _build_common_args(self, policy: RuntimePolicy | None = None) -> list[str]:
        model = (
            self.resolved_config.resolved_model
            if self.resolved_config is not None
            else self._legacy_model()
        )
        if not model:
            raise ConfigError("ClaudeRuntime 缺少 resolved model，请先执行 `take-root configure`")
        args = [
            "--append-system-prompt",
            self.persona.system_prompt,
            "--model",
            model,
        ]
        raw_effort = (
            self.resolved_config.effort
            if self.resolved_config is not None
            else self._legacy_reasoning()
        )
        if raw_effort:
            args.extend(["--effort", raw_effort])
        if policy is not None and policy.mode == "review_only":
            if policy.output_path is None:
                raise ConfigError("review_only policy requires output_path")
            tool_list = "Read,Grep,Glob,LS,Write"
            allowed = f"Read,Grep,Glob,LS,Write({policy.output_path})"
            args.extend(
                [
                    "--tools",
                    tool_list,
                    "--allowedTools",
                    allowed,
                    "--permission-mode",
                    "acceptEdits",
                ]
            )
        return args

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 3600,
        policy: RuntimePolicy | None = None,
    ) -> RuntimeCallResult:
        cmd = ["claude", "-p", boot_message, *self._build_common_args(policy)]
        return self._run_noninteractive_with_policy(
            cmd,
            cwd,
            timeout_sec,
            env=self._subprocess_env(),
        )

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
            env=self._subprocess_env(),
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
