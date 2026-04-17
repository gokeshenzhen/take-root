from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from take_root.errors import ConfigError, RuntimeCallError
from take_root.persona import Persona

if TYPE_CHECKING:
    from take_root.config import ResolvedRuntimeConfig

LOGGER = logging.getLogger(__name__)

TRANSIENT_PATTERNS = (
    re.compile(r"rate[ -]?limit", re.IGNORECASE),
    re.compile(r"\b429\b", re.IGNORECASE),
    re.compile(r"econnreset", re.IGNORECASE),
    re.compile(r"etimedout", re.IGNORECASE),
    re.compile(r"eai_again", re.IGNORECASE),
    re.compile(r"temporarily unavailable", re.IGNORECASE),
    re.compile(r"service unavailable", re.IGNORECASE),
)


@dataclass(slots=True)
class RuntimeCallResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    mode: Literal["default", "review_only"] = "default"
    output_path: Path | None = None
    allow_shell: bool = True

    @classmethod
    def review_only(cls, output_path: Path) -> RuntimePolicy:
        return cls(
            mode="review_only",
            output_path=output_path.resolve(),
            allow_shell=False,
        )


@dataclass(slots=True)
class RuntimeConfig:
    plan_timeout_sec: int = 900
    code_timeout_sec: int = 1800
    test_timeout_sec: int = 3600
    retries: int = 2
    retry_backoff_sec: tuple[int, int] = (10, 30)

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        def _read_int(name: str, default: int) -> int:
            value = os.getenv(name)
            if value is None:
                return default
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ConfigError(f"Invalid integer env {name}={value!r}") from exc
            if parsed <= 0:
                raise ConfigError(f"Invalid non-positive timeout {name}={value!r}")
            return parsed

        return cls(
            plan_timeout_sec=_read_int("TAKE_ROOT_TIMEOUT_PLAN", 900),
            code_timeout_sec=_read_int("TAKE_ROOT_TIMEOUT_CODE", 1800),
            test_timeout_sec=_read_int("TAKE_ROOT_TIMEOUT_TEST", 3600),
        )


class BaseRuntime(ABC):
    """One runtime instance per persona call."""

    def __init__(
        self,
        persona: Persona,
        project_root: Path,
        config: RuntimeConfig | None = None,
        resolved_config: ResolvedRuntimeConfig | None = None,
    ) -> None:
        self.persona = persona
        self.project_root = project_root
        self.config = config if config is not None else RuntimeConfig.from_env()
        self.resolved_config = resolved_config

    @classmethod
    @abstractmethod
    def check_available(cls) -> None:
        """Validate runtime CLI installation."""

    @abstractmethod
    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 3600,
        policy: RuntimePolicy | None = None,
    ) -> RuntimeCallResult:
        """Run a non-interactive runtime call."""

    @abstractmethod
    def call_interactive(
        self,
        boot_message: str,
        cwd: Path,
    ) -> RuntimeCallResult:
        """Run an interactive runtime call."""

    def _is_transient_error(self, stderr: str) -> bool:
        return any(pattern.search(stderr) for pattern in TRANSIENT_PATTERNS)

    def _log_runtime_start(
        self,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
        env: dict[str, str] | None,
    ) -> None:
        LOGGER.debug(
            "runtime start: persona=%s runtime=%s cwd=%s timeout=%ss cmd=%s env_keys=%s",
            self.persona.name,
            self.__class__.__name__,
            cwd,
            timeout_sec,
            _summarize_cmd(cmd),
            sorted(env.keys()) if env is not None else [],
        )

    def _log_runtime_result(self, result: RuntimeCallResult) -> None:
        LOGGER.debug(
            "runtime result: persona=%s runtime=%s exit_code=%s "
            "duration=%.3fs stdout=%dB stderr=%dB",
            self.persona.name,
            self.__class__.__name__,
            result.exit_code,
            result.duration_sec,
            len(result.stdout),
            len(result.stderr),
        )
        if result.stdout:
            LOGGER.debug("runtime stdout preview: %s", _preview_text(result.stdout))
        if result.stderr:
            LOGGER.debug("runtime stderr preview: %s", _preview_text(result.stderr))

    def _run_noninteractive_with_policy(
        self,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
        env: dict[str, str] | None = None,
    ) -> RuntimeCallResult:
        attempt = 0
        while True:
            started = time.monotonic()
            self._log_runtime_start(cmd, cwd, timeout_sec, env)
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=cwd,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout_sec,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                partial_stdout = (
                    exc.stdout
                    if isinstance(exc.stdout, str)
                    else (exc.stdout.decode() if exc.stdout else "")
                )
                partial_stderr = (
                    exc.stderr
                    if isinstance(exc.stderr, str)
                    else (exc.stderr.decode() if exc.stderr else "")
                )
                LOGGER.debug(
                    "runtime timeout: persona=%s runtime=%s timeout=%ss "
                    "partial_stdout=%s partial_stderr=%s",
                    self.persona.name,
                    self.__class__.__name__,
                    timeout_sec,
                    _preview_text(partial_stdout),
                    _preview_text(partial_stderr),
                )
                raise RuntimeCallError(f"timeout after {timeout_sec}s") from exc
            duration = time.monotonic() - started
            result = RuntimeCallResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_sec=duration,
            )
            self._log_runtime_result(result)
            if result.exit_code == 0:
                return result
            if attempt >= self.config.retries or not self._is_transient_error(result.stderr):
                tail = result.stderr[-2048:]
                raise RuntimeCallError(
                    f"runtime exited {result.exit_code}: {tail.strip() or '<empty stderr>'}"
                )
            delay = self.config.retry_backoff_sec[
                min(attempt, len(self.config.retry_backoff_sec) - 1)
            ]
            time.sleep(delay)
            attempt += 1

    def _legacy_model(self) -> str | None:
        value = self.persona.raw_frontmatter.get("model")
        if isinstance(value, str) and value:
            return value
        return None

    def _legacy_reasoning(self) -> str | None:
        value = self.persona.raw_frontmatter.get("reasoning")
        if isinstance(value, str) and value:
            return value
        return None

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.resolved_config is None:
            return env
        for key in self.resolved_config.cleared_env_vars:
            env.pop(key, None)
        env.update(self.resolved_config.env)
        return env


def _preview_text(text: str, limit: int = 400) -> str:
    normalized = text.replace("\n", "\\n")
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}...(+{len(normalized) - limit} chars)"


def _summarize_cmd(cmd: list[str], max_items: int = 10) -> str:
    items = [_preview_text(item, limit=120) for item in cmd[:max_items]]
    if len(cmd) > max_items:
        items.append(f"...(+{len(cmd) - max_items} args)")
    return "[" + ", ".join(items) + "]"
