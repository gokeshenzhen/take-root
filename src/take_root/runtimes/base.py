from __future__ import annotations

import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from take_root.errors import ConfigError, RuntimeCallError
from take_root.persona import Persona

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
    ) -> None:
        self.persona = persona
        self.project_root = project_root
        self.config = config if config is not None else RuntimeConfig.from_env()

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

    def _run_noninteractive_with_policy(
        self,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
    ) -> RuntimeCallResult:
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=cwd,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout_sec,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeCallError(f"timeout after {timeout_sec}s") from exc
            duration = time.monotonic() - started
            result = RuntimeCallResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_sec=duration,
            )
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
