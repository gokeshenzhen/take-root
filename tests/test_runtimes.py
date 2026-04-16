from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from take_root.config import ResolvedRuntimeConfig
from take_root.errors import RuntimeCallError
from take_root.persona import Persona
from take_root.runtimes.base import BaseRuntime, RuntimeCallResult, RuntimeConfig, RuntimePolicy
from take_root.runtimes.claude import ClaudeRuntime
from take_root.runtimes.codex import CodexRuntime


def _persona(runtime: str, reasoning: str | None = "high") -> Persona:
    return Persona(
        name="x",
        role="r",
        runtime=runtime,
        interactive=False,
        output_artifacts=["a.md"],
        system_prompt="SYS",
        source_path=Path("/tmp/p.md"),
        raw_frontmatter={"model": "m1", "reasoning": reasoning} if reasoning else {"model": "m1"},
    )


def _resolved_config(
    *,
    runtime_name: str = "claude",
    model: str = "m1",
    effort: str | None = "high",
    env: dict[str, str] | None = None,
) -> ResolvedRuntimeConfig:
    return ResolvedRuntimeConfig(
        runtime_name=runtime_name,
        provider_name="qwen",
        provider_kind="anthropic_compatible",
        base_url="https://example.test",
        model_selector="sonnet",
        resolved_model=model,
        effort=effort,
        token_source="env:TOKEN",
        env=env or {"ANTHROPIC_MODEL": model},
        cleared_env_vars=("ANTHROPIC_MODEL",),
    )


class _DummyRuntime(BaseRuntime):
    @classmethod
    def check_available(cls) -> None:
        return

    def call_noninteractive(
        self,
        boot_message: str,
        cwd: Path,
        timeout_sec: int = 3600,
        policy: RuntimePolicy | None = None,
    ) -> RuntimeCallResult:
        del policy
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
        self: ClaudeRuntime,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
        env: dict[str, str] | None = None,
    ) -> RuntimeCallResult:
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout_sec"] = timeout_sec
        captured["env"] = env
        return RuntimeCallResult(0, "ok", "", 0.1)

    monkeypatch.setattr(ClaudeRuntime, "_run_noninteractive_with_policy", _fake_policy)
    runtime = ClaudeRuntime(
        _persona("claude", reasoning="minimal"),
        tmp_path,
        resolved_config=_resolved_config(
            runtime_name="claude",
            model="qwen3.6-plus",
            effort="minimal",
        ),
    )
    runtime.call_noninteractive("BOOT", tmp_path, timeout_sec=123)
    cmd = captured["cmd"]
    assert cmd[:3] == ["claude", "-p", "BOOT"]
    assert "--append-system-prompt" in cmd
    assert "--model" in cmd
    assert "--effort" in cmd
    assert "qwen3.6-plus" in cmd
    assert "low" in cmd


def test_claude_runtime_review_only_policy_builds_restricted_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_policy(
        self: ClaudeRuntime,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
        env: dict[str, str] | None = None,
    ) -> RuntimeCallResult:
        captured["cmd"] = cmd
        del self, cwd, timeout_sec, env
        return RuntimeCallResult(0, "ok", "", 0.1)

    monkeypatch.setattr(ClaudeRuntime, "_run_noninteractive_with_policy", _fake_policy)
    runtime = ClaudeRuntime(
        _persona("claude"),
        tmp_path,
        resolved_config=_resolved_config(runtime_name="claude"),
    )
    output_path = tmp_path / "artifact.md"
    runtime.call_noninteractive(
        "BOOT",
        tmp_path,
        policy=RuntimePolicy.review_only(output_path),
    )
    cmd = captured["cmd"]
    assert "--tools" in cmd
    assert "--allowedTools" in cmd
    assert any(f"Write({output_path.resolve()})" in item for item in cmd)
    assert "--permission-mode" in cmd


def test_codex_runtime_builds_expected_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_policy(
        self: CodexRuntime,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
        env: dict[str, str] | None = None,
    ) -> RuntimeCallResult:
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["timeout_sec"] = timeout_sec
        captured["env"] = env
        return RuntimeCallResult(0, "ok", "", 0.1)

    monkeypatch.setattr(CodexRuntime, "_run_noninteractive_with_policy", _fake_policy)
    runtime = CodexRuntime(
        _persona("codex", reasoning="high"),
        tmp_path,
        resolved_config=_resolved_config(
            runtime_name="codex",
            model="gpt-5.4",
            effort="high",
        ),
    )
    runtime.call_noninteractive("BOOT", tmp_path, timeout_sec=321)
    cmd = captured["cmd"]
    assert cmd[:3] == ["codex", "exec", "--skip-git-repo-check"]
    assert "-m" in cmd
    assert "BOOT" == cmd[-1]
    assert any(item.startswith("developer_instructions=") for item in cmd)
    assert any(item.startswith("model_reasoning_effort=") for item in cmd)


def test_codex_runtime_review_only_policy_routes_last_message_to_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_policy(
        self: CodexRuntime,
        cmd: list[str],
        cwd: Path,
        timeout_sec: int,
        env: dict[str, str] | None = None,
    ) -> RuntimeCallResult:
        captured["cmd"] = cmd
        del self, cwd, timeout_sec, env
        return RuntimeCallResult(0, "ok", "", 0.1)

    monkeypatch.setattr(CodexRuntime, "_run_noninteractive_with_policy", _fake_policy)
    runtime = CodexRuntime(
        _persona("codex", reasoning="high"),
        tmp_path,
        resolved_config=_resolved_config(
            runtime_name="codex",
            model="gpt-5.4",
            effort="high",
        ),
    )
    output_path = tmp_path / "artifact.md"
    runtime.call_noninteractive(
        "BOOT",
        tmp_path,
        policy=RuntimePolicy.review_only(output_path),
    )
    cmd = captured["cmd"]
    assert "--sandbox" in cmd
    assert "read-only" in cmd
    assert "--output-last-message" in cmd
    assert str(output_path.resolve()) in cmd


def test_codex_runtime_interactive_builds_expected_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = args[0]
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(time, "monotonic", lambda: 10.0)
    runtime = CodexRuntime(
        _persona("codex", reasoning="high"),
        tmp_path,
        resolved_config=_resolved_config(
            runtime_name="codex",
            model="gpt-5.4",
            effort="high",
        ),
    )
    result = runtime.call_interactive("BOOT", tmp_path)
    cmd = captured["cmd"]
    assert cmd[0] == "codex"
    assert "exec" not in cmd
    assert "-m" in cmd
    assert "BOOT" == cmd[-1]
    assert result.exit_code == 0


def test_base_runtime_subprocess_env_clears_and_injects(tmp_path: Path) -> None:
    runtime = _DummyRuntime(
        _persona("claude"),
        tmp_path,
        resolved_config=_resolved_config(
            runtime_name="claude",
            env={"ANTHROPIC_MODEL": "qwen3.6-plus"},
        ),
    )
    env = runtime._subprocess_env()
    assert env["ANTHROPIC_MODEL"] == "qwen3.6-plus"
