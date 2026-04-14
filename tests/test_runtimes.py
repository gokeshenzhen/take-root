from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from take_root.errors import RuntimeCallError
from take_root.persona import Persona
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult, RuntimeConfig
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime


def _persona(runtime: str, reasoning: str | None = "high") -> Persona:
    return Persona(
        name="x",
        role="r",
        runtime=runtime,
        model="m1",
        reasoning=reasoning,
        interactive=False,
        output_artifacts=["a.md"],
        system_prompt="SYS",
        source_path=Path("/tmp/p.md"),
        raw_frontmatter={},
    )


class _DummyRuntime(BaseRuntime):
    @classmethod
    def check_available(cls) -> None:
        return

    def call_noninteractive(
        self, boot_message: str, cwd: Path, timeout_sec: int = 3600
    ) -> RuntimeCallResult:
        return self._run_noninteractive_with_policy(["dummy", boot_message], cwd, timeout_sec)

    def call_interactive(self, boot_message: str, cwd: Path) -> RuntimeCallResult:
        raise NotImplementedError


def test_base_runtime_retries_transient(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[int] = []

    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        calls.append(1)
        if len(calls) == 1:
            return subprocess.CompletedProcess(["dummy"], 1, "", "429 rate limit")
        return subprocess.CompletedProcess(["dummy"], 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr("time.sleep", lambda _: None)
    runtime = _DummyRuntime(_persona("codex"), tmp_path, config=RuntimeConfig(retries=2))
    result = runtime.call_noninteractive("hi", tmp_path, timeout_sec=1)
    assert result.exit_code == 0
    assert len(calls) == 2


def test_base_runtime_timeout_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise subprocess.TimeoutExpired(cmd=["dummy"], timeout=1)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    runtime = _DummyRuntime(_persona("codex"), tmp_path)
    with pytest.raises(RuntimeCallError):
        runtime.call_noninteractive("hi", tmp_path, timeout_sec=1)


def test_claude_runtime_builds_expected_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_policy(
        self: ClaudeRuntime, cmd: list[str], cwd: Path, timeout_sec: int
    ) -> RuntimeCallResult:
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout_sec"] = timeout_sec
        return RuntimeCallResult(0, "ok", "", 0.1)

    monkeypatch.setattr(ClaudeRuntime, "_run_noninteractive_with_policy", _fake_policy)
    runtime = ClaudeRuntime(_persona("claude", reasoning="minimal"), tmp_path)
    runtime.call_noninteractive("BOOT", tmp_path, timeout_sec=123)
    cmd = captured["cmd"]
    assert cmd[:3] == ["claude", "-p", "BOOT"]
    assert "--append-system-prompt" in cmd
    assert "--model" in cmd
    assert "--effort" in cmd
    assert "low" in cmd


def test_codex_runtime_builds_expected_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_policy(
        self: CodexRuntime, cmd: list[str], cwd: Path, timeout_sec: int
    ) -> RuntimeCallResult:
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout_sec"] = timeout_sec
        return RuntimeCallResult(0, "ok", "", 0.1)

    monkeypatch.setattr(CodexRuntime, "_run_noninteractive_with_policy", _fake_policy)
    runtime = CodexRuntime(_persona("codex", reasoning="high"), tmp_path)
    runtime.call_noninteractive("BOOT", tmp_path, timeout_sec=321)
    cmd = captured["cmd"]
    assert cmd[:3] == ["codex", "exec", "--skip-git-repo-check"]
    assert "-m" in cmd
    assert "BOOT" == cmd[-1]
    assert any(item.startswith("developer_instructions=") for item in cmd)
    assert any(item.startswith("model_reasoning_effort=") for item in cmd)


def test_codex_runtime_interactive_not_supported(tmp_path: Path) -> None:
    runtime = CodexRuntime(_persona("codex"), tmp_path)
    with pytest.raises(NotImplementedError):
        runtime.call_interactive("boot", tmp_path)
