from __future__ import annotations

from pathlib import Path

import pytest

from take_root.config import (
    CLAUDE_OFFICIAL_DEFAULT_MODELS,
    ActorRouteConfig,
    ProviderConfig,
    TakeRootConfig,
    default_take_root_config,
    load_config,
    masked_runtime_env_summary,
    resolve_persona_runtime_config,
    save_config,
)
from take_root.errors import ConfigError


def test_load_and_save_config_roundtrip(tmp_path: Path) -> None:
    config = default_take_root_config()
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.schema_version == 1
    assert loaded.init.provider == "claude_official"
    assert loaded.personas["lucy"].provider == "codex_official"


def test_resolve_persona_runtime_config_alias_for_compatible_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    config = default_take_root_config()
    save_config(tmp_path, config)
    resolved = resolve_persona_runtime_config(config, "jeff")
    assert resolved.runtime_name == "claude"
    assert resolved.provider_name == "qwen"
    assert resolved.resolved_model == "qwen3.6-plus"
    assert resolved.env["ANTHROPIC_BASE_URL"].startswith("https://dashscope")
    assert resolved.env["ANTHROPIC_AUTH_TOKEN"] == "abcd1234token"


def test_resolve_persona_runtime_config_clears_env_for_official(tmp_path: Path) -> None:
    config = default_take_root_config()
    resolved = resolve_persona_runtime_config(config, "lucy")
    assert resolved.provider_name == "codex_official"
    assert resolved.runtime_name == "codex"
    assert resolved.resolved_model == "gpt-5.4"
    assert resolved.env == {}
    assert "ANTHROPIC_AUTH_TOKEN" in resolved.cleared_env_vars


def test_resolve_persona_runtime_config_alias_for_claude_official(tmp_path: Path) -> None:
    config = default_take_root_config()
    config = TakeRootConfig(
        schema_version=config.schema_version,
        providers=config.providers,
        init=ActorRouteConfig(provider="claude_official", model="opus", effort="medium"),
        personas=config.personas,
    )
    resolved = resolve_persona_runtime_config(
        TakeRootConfig(
            schema_version=config.schema_version,
            providers=config.providers,
            init=config.init,
            personas={
                **config.personas,
                "jeff": ActorRouteConfig(
                    provider="claude_official",
                    model="opus",
                    effort="medium",
                ),
            },
        ),
        "jeff",
    )
    assert resolved.resolved_model == "claude-opus-4-7"


def test_resolve_persona_runtime_config_missing_token_raises(tmp_path: Path) -> None:
    config = default_take_root_config()
    with pytest.raises(ConfigError):
        resolve_persona_runtime_config(config, "jeff")


def test_resolve_persona_runtime_config_unknown_provider_raises(tmp_path: Path) -> None:
    config = TakeRootConfig(
        schema_version=1,
        providers={"claude_official": ProviderConfig(kind="claude_official")},
        init=ActorRouteConfig(provider="claude_official", model="opus", effort="medium"),
        personas={"jeff": ActorRouteConfig(provider="missing", model="sonnet", effort="medium")},
    )
    with pytest.raises(ConfigError):
        resolve_persona_runtime_config(config, "jeff")


def test_resolve_persona_runtime_config_missing_alias_mapping_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    config = TakeRootConfig(
        schema_version=1,
        providers={
            "qwen": ProviderConfig(
                kind="anthropic_compatible",
                base_url="https://example.test",
                auth_token_env="ANTHROPIC_AUTH_TOKEN_QWEN",
                default_models={"opus": "x"},
            )
        },
        init=ActorRouteConfig(provider="qwen", model="opus", effort="medium"),
        personas={"jeff": ActorRouteConfig(provider="qwen", model="sonnet", effort="medium")},
    )
    with pytest.raises(ConfigError):
        resolve_persona_runtime_config(config, "jeff")


def test_masked_runtime_env_summary_masks_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_QWEN", "abcd1234token")
    config = TakeRootConfig(
        schema_version=1,
        providers={
            "qwen": ProviderConfig(
                kind="anthropic_compatible",
                base_url="https://dashscope.aliyuncs.com/apps/anthropic",
                auth_token_env="ANTHROPIC_AUTH_TOKEN_QWEN",
                default_models={
                    "opus": "qwen3-max",
                    "sonnet": "qwen3.6-plus",
                    "haiku": "qwen3.5-flash",
                },
            )
        },
        init=ActorRouteConfig(provider="qwen", model="sonnet", effort="medium"),
        personas={"jeff": ActorRouteConfig(provider="qwen", model="sonnet", effort="medium")},
    )
    resolved = resolve_persona_runtime_config(config, "jeff")
    summary = masked_runtime_env_summary(resolved)
    assert summary["ANTHROPIC_AUTH_TOKEN"] == "abcd...oken"


def test_resolve_persona_runtime_config_uses_direct_api_key() -> None:
    config = default_take_root_config()
    qwen = config.providers["qwen"]
    config = TakeRootConfig(
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
    )
    resolved = resolve_persona_runtime_config(config, "jeff")
    assert resolved.token_source == "config:providers.qwen.auth_token"
    assert resolved.env["ANTHROPIC_AUTH_TOKEN"] == "abcd1234token"


def test_resolve_persona_runtime_config_rejects_legacy_kimi_k25(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN_KIMI", "moonshot-token")
    config = default_take_root_config()
    config = TakeRootConfig(
        schema_version=config.schema_version,
        providers=config.providers,
        init=config.init,
        personas={
            **config.personas,
            "neo": ActorRouteConfig(provider="kimi", model="kimi-k2.5", effort="high"),
        },
    )
    with pytest.raises(ConfigError):
        resolve_persona_runtime_config(config, "neo")


def test_default_take_root_config_uses_upgraded_effort_defaults() -> None:
    config = default_take_root_config()
    assert CLAUDE_OFFICIAL_DEFAULT_MODELS["opus"] == "claude-opus-4-7"
    assert config.personas["robin"].effort == "xhigh"
    assert config.personas["neo"].effort == "xhigh"
    assert config.personas["lucy"].effort == "xhigh"
    assert config.personas["peter"].effort == "xhigh"


def test_load_config_rejects_minimal_effort_with_configure_hint(tmp_path: Path) -> None:
    path = tmp_path / ".take_root" / "config.yaml"
    save_config(tmp_path, default_take_root_config())
    text = path.read_text(encoding="utf-8").replace("effort: medium", "effort: minimal", 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match=r"take-root configure"):
        load_config(tmp_path)


def test_load_config_rejects_codex_max_effort_with_allowed_values(tmp_path: Path) -> None:
    config = default_take_root_config()
    config = TakeRootConfig(
        schema_version=config.schema_version,
        providers=config.providers,
        init=ActorRouteConfig(provider="codex_official", model="opus", effort="max"),
        personas=config.personas,
    )
    save_config(tmp_path, config)

    with pytest.raises(ConfigError, match=r"low, medium, high, xhigh"):
        load_config(tmp_path)


def test_load_config_allows_claude_max_effort(tmp_path: Path) -> None:
    config = default_take_root_config()
    config = TakeRootConfig(
        schema_version=config.schema_version,
        providers=config.providers,
        init=ActorRouteConfig(provider="claude_official", model="opus", effort="max"),
        personas=config.personas,
    )
    save_config(tmp_path, config)

    loaded = load_config(tmp_path)
    assert loaded.init.effort == "max"
