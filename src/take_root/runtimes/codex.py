from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from take_root.errors import ConfigError, RuntimeCallError
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult, RuntimePolicy

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
        policy: RuntimePolicy | None = None,
    ) -> RuntimeCallResult:
        cmd = self._build_common_args(interactive=False, policy=policy)
        cmd.append(boot_message)
        return self._run_noninteractive_with_policy(
            cmd,
            cwd,
            timeout_sec,
            env=self._subprocess_env(),
        )

    def _build_common_args(
        self,
        *,
        interactive: bool,
        policy: RuntimePolicy | None = None,
    ) -> list[str]:
        model = (
            self.resolved_config.resolved_model
            if self.resolved_config is not None
            else self._legacy_model()
        )
        if not model:
            raise ConfigError("CodexRuntime 缺少 resolved model，请先执行 `take-root configure`")
        cmd = ["codex"]
        if not interactive:
            cmd.extend(["exec", "--skip-git-repo-check"])
            if policy is not None and policy.mode == "review_only":
                if policy.output_path is None:
                    raise ConfigError("review_only policy requires output_path")
                cmd.extend(
                    [
                        "--sandbox",
                        "read-only",
                        "--output-last-message",
                        str(policy.output_path),
                    ]
                )
        cmd.extend(
            [
                "-m",
                model,
                "-c",
                f"developer_instructions={_as_toml_string(self.persona.system_prompt)}",
            ]
        )
        raw_effort = (
            self.resolved_config.effort
            if self.resolved_config is not None
            else self._legacy_reasoning()
        )
        if raw_effort:
            effort = raw_effort.lower()
            if effort in CODEX_REASONING_ALLOWED:
                cmd.extend(
                    [
                        "-c",
                        f"model_reasoning_effort={_as_toml_string(effort)}",
                    ]
                )
        return cmd

    def call_interactive(
        self,
        boot_message: str,
        cwd: Path,
    ) -> RuntimeCallResult:
        started = time.monotonic()
        cmd = self._build_common_args(interactive=True)
        cmd.append(boot_message)
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            check=False,
            env=self._subprocess_env(),
        )
        duration = time.monotonic() - started
        if completed.returncode != 0:
            raise RuntimeCallError(f"interactive Codex exited with code {completed.returncode}")
        return RuntimeCallResult(
            exit_code=completed.returncode,
            stdout="",
            stderr="",
            duration_sec=duration,
        )
