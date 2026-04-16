from __future__ import annotations

import os
from pathlib import Path

from take_root.config import (
    ActorRouteConfig,
    ProviderConfig,
    TakeRootConfig,
    default_take_root_config,
    save_config,
)
from take_root.doctor import run_doctor


def _write_fake_claude(bin_dir: Path) -> None:
    script = (
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--version" ]; then\n'
        "  printf 'claude fake\\n'\n"
        "  exit 0\n"
        "fi\n"
        'printf \'%s\\n\' "$@" > "$TRACE_DIR/argv.txt"\n'
        'env | sort > "$TRACE_DIR/env.txt"\n'
        "printf 'provider-check-ok\\n'\n"
    )
    path = bin_dir / "claude"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _write_fake_codex(bin_dir: Path) -> None:
    script = (
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--version" ]; then\n'
        "  printf 'codex fake\\n'\n"
        "  exit 0\n"
        "fi\n"
        'printf \'%s\\n\' "$@" > "$TRACE_DIR/codex_argv.txt"\n'
        'env | sort > "$TRACE_DIR/codex_env.txt"\n'
        "printf 'provider-check-ok\\n'\n"
    )
    path = bin_dir / "codex"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def test_doctor_injects_anthropic_compatible_env(monkeypatch, tmp_path: Path, capsys) -> None:
    bin_dir = tmp_path / "bin"
    trace_dir = tmp_path / "trace"
    bin_dir.mkdir()
    trace_dir.mkdir()
    _write_fake_claude(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    save_config(tmp_path, default_take_root_config())

    run_doctor(tmp_path, "jeff")

    env_text = (trace_dir / "env.txt").read_text(encoding="utf-8")
    assert "ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic" in env_text
    assert "ANTHROPIC_MODEL=qwen3.6-plus" in env_text

    summary = (tmp_path / ".take_root" / "doctor" / "jeff_runtime_env.json").read_text(
        encoding="utf-8"
    )
    assert "abcd...oken" in summary
    assert "abcd1234token" not in summary
    output = capsys.readouterr().out
    assert "provider: qwen" in output
    assert "call_status: success" in output


def test_doctor_clears_inherited_provider_env(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    trace_dir = tmp_path / "trace"
    bin_dir.mkdir()
    trace_dir.mkdir()
    _write_fake_claude(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://leak.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "leaked-token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "wrong-model")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    config = default_take_root_config()
    save_config(
        tmp_path,
        TakeRootConfig(
            schema_version=config.schema_version,
            providers=config.providers,
            init=config.init,
            personas={
                **config.personas,
                "jeff": ActorRouteConfig(
                    provider="claude_official",
                    model="sonnet",
                    effort="medium",
                ),
            },
        ),
    )

    run_doctor(tmp_path, "jeff")

    env_text = (trace_dir / "env.txt").read_text(encoding="utf-8")
    assert "ANTHROPIC_BASE_URL=" not in env_text
    assert "ANTHROPIC_AUTH_TOKEN=" not in env_text
    assert "ANTHROPIC_MODEL=" not in env_text


def test_doctor_uses_codex_runtime_for_codex_provider(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    trace_dir = tmp_path / "trace"
    bin_dir.mkdir()
    trace_dir.mkdir()
    _write_fake_codex(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    save_config(tmp_path, default_take_root_config())

    run_doctor(tmp_path, "ruby")

    argv_text = (trace_dir / "codex_argv.txt").read_text(encoding="utf-8")
    assert "exec" in argv_text
    assert "gpt-5.4" in argv_text


def test_doctor_supports_api_key_saved_in_config(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    trace_dir = tmp_path / "trace"
    bin_dir.mkdir()
    trace_dir.mkdir()
    _write_fake_claude(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    config = default_take_root_config()
    qwen = config.providers["qwen"]
    save_config(
        tmp_path,
        TakeRootConfig(
            schema_version=config.schema_version,
            providers={
                **config.providers,
                "qwen": ProviderConfig(
                    kind=qwen.kind,
                    base_url=qwen.base_url,
                    auth_token_env=qwen.auth_token_env,
                    auth_token="abcd1234token",
                    default_models=qwen.default_models,
                ),
            },
            init=config.init,
            personas=config.personas,
        ),
    )

    run_doctor(tmp_path, "jeff")

    env_text = (trace_dir / "env.txt").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=abcd1234token" in env_text


def test_doctor_all_runs_all_personas(monkeypatch, tmp_path: Path, capsys) -> None:
    bin_dir = tmp_path / "bin"
    trace_dir = tmp_path / "trace"
    bin_dir.mkdir()
    trace_dir.mkdir()
    _write_fake_claude(bin_dir)
    _write_fake_codex(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_KIMI", "moonshot-token")
    save_config(tmp_path, default_take_root_config())

    result = run_doctor(tmp_path, "all")

    output = capsys.readouterr().out
    assert "persona: jeff" in output
    assert "persona: amy" in output
    assert output.count("call_status: success") == 6
    assert "summary: 6/6 success, 0 skipped" in output
    assert result["persona"] == "all"
    assert len(result["results"]) == 6
