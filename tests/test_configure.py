from __future__ import annotations

from pathlib import Path

import pytest

from take_root.config import (
    ActorRouteConfig,
    ProviderConfig,
    default_take_root_config,
    load_config,
    save_config,
)
from take_root.errors import ConfigError
from take_root.phases.configure import (
    _prompt_api_key,
    _prompt_model,
    _prompt_route,
    _select_option,
    run_configure,
)


def test_select_option_returns_default_on_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "take_root.phases.configure.select_option",
        lambda prompt, options, default: default,
    )
    selected = _select_option("选择 provider", ["a", "b", "c"], "b")
    assert selected == "b"


def test_prompt_api_key_requires_value_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["", "secret-key"])
    monkeypatch.setattr(
        "take_root.phases.configure.ask",
        lambda prompt, default=None: next(answers),
    )
    provider = _prompt_api_key(
        "qwen",
        ProviderConfig(
            kind="anthropic_compatible",
            base_url="https://example.test",
            auth_token_env="ANTHROPIC_AUTH_TOKEN",
        ),
    )
    assert provider.auth_token == "secret-key"


def test_run_configure_uses_numbered_selections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save_config(tmp_path, default_take_root_config())
    selections = iter(["codex_official", "gpt-5.4", "xhigh (Extra high)"])
    monkeypatch.setattr(
        "take_root.phases.configure.select_option",
        lambda prompt, options, default: next(selections),
    )
    run_configure(tmp_path, section="init")
    config = load_config(tmp_path)
    assert config.init.provider == "codex_official"
    assert config.init.model == "gpt-5.4"
    assert config.init.effort == "xhigh"


def test_run_configure_keeps_existing_api_key_on_enter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = default_take_root_config()
    qwen = config.providers["qwen"]
    config = config.__class__(
        schema_version=config.schema_version,
        providers={
            **config.providers,
            "qwen": ProviderConfig(
                kind=qwen.kind,
                base_url=qwen.base_url,
                auth_token_env=qwen.auth_token_env,
                auth_token="saved-key",
                default_models=qwen.default_models,
            ),
        },
        init=config.init,
        personas=config.personas,
    )
    save_config(tmp_path, config)
    answers = iter(["", "kimi-key"])
    selections = iter(
        [
            "qwen3-max",
            "qwen3.6-plus",
            "qwen3.5-flash",
            "kimi-k2.5",
            "kimi-k2.5",
            "kimi-k2.5",
            "no",
        ]
    )
    monkeypatch.setattr(
        "take_root.phases.configure.ask",
        lambda prompt, default=None: next(answers),
    )
    monkeypatch.setattr(
        "take_root.phases.configure.select_option",
        lambda prompt, options, default: next(selections),
    )
    run_configure(tmp_path, section="providers")
    loaded = load_config(tmp_path)
    assert loaded.providers["qwen"].auth_token == "saved-key"


def test_prompt_model_allows_custom_model_for_claude_official(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections = iter(["(自定义)"])
    monkeypatch.setattr(
        "take_root.phases.configure.select_option",
        lambda prompt, options, default: next(selections),
    )
    monkeypatch.setattr(
        "take_root.phases.configure.ask",
        lambda prompt, default=None: "claude-sonnet-4-6",
    )
    selected = _prompt_model(
        "claude_official",
        model_hint="opus/sonnet/haiku 或具体模型名",
        model_default="sonnet",
    )
    assert selected == "claude-sonnet-4-6"


def test_run_configure_invalid_section_raises_config_error(tmp_path: Path) -> None:
    save_config(tmp_path, default_take_root_config())
    with pytest.raises(ConfigError):
        run_configure(tmp_path, section="invalid")


def test_run_configure_effort_options_follow_codex_provider_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save_config(tmp_path, default_take_root_config())
    effort_options: list[str] = []

    def _fake_select(prompt: str, options: list[str], default: str) -> str:
        if prompt == "选择 provider":
            return "codex_official"
        if prompt == "选择 effort":
            effort_options.extend(options)
        return default

    monkeypatch.setattr("take_root.phases.configure.select_option", _fake_select)
    run_configure(tmp_path, section="init")
    assert effort_options == ["low", "medium", "high", "xhigh (Extra high)"]


def test_run_configure_effort_options_follow_claude_provider_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    save_config(tmp_path, default_take_root_config())
    effort_options: list[str] = []

    def _fake_select(prompt: str, options: list[str], default: str) -> str:
        if prompt == "选择 provider":
            return "qwen"
        if prompt == "选择 effort":
            effort_options.extend(options)
        return default

    monkeypatch.setattr("take_root.phases.configure.select_option", _fake_select)
    run_configure(tmp_path, section="init")
    assert effort_options == ["low", "medium", "high", "xhigh (Extra high)", "max"]


def test_prompt_route_repicks_effort_when_switching_to_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = default_take_root_config()
    prompts: list[tuple[str, list[str], str]] = []
    notices: list[str] = []

    def _fake_select(prompt: str, options: list[str], default: str) -> str:
        prompts.append((prompt, options, default))
        if prompt == "选择 provider":
            return "codex_official"
        return default

    monkeypatch.setattr("take_root.phases.configure.select_option", _fake_select)
    monkeypatch.setattr("take_root.phases.configure.info", notices.append)
    route = _prompt_route(
        "lucy",
        ActorRouteConfig(provider="claude_official", model="opus", effort="max"),
        config.providers,
        list(config.providers),
        allow_codex=True,
    )

    effort_prompt = next(call for call in prompts if call[0] == "选择 effort")
    assert effort_prompt[1] == ["low", "medium", "high", "xhigh (Extra high)"]
    assert effort_prompt[2] == "medium"
    assert any("不支持之前的 effort" in notice for notice in notices)
    assert route.provider == "codex_official"
    assert route.effort == "medium"


def test_prompt_route_keeps_existing_effort_when_switching_to_codex_if_still_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = default_take_root_config()
    prompts: list[tuple[str, list[str], str]] = []
    notices: list[str] = []

    def _fake_select(prompt: str, options: list[str], default: str) -> str:
        prompts.append((prompt, options, default))
        if prompt == "选择 provider":
            return "codex_official"
        return default

    monkeypatch.setattr("take_root.phases.configure.select_option", _fake_select)
    monkeypatch.setattr("take_root.phases.configure.info", notices.append)
    route = _prompt_route(
        "lucy",
        ActorRouteConfig(provider="claude_official", model="opus", effort="high"),
        config.providers,
        list(config.providers),
        allow_codex=True,
    )

    effort_prompt = next(call for call in prompts if call[0] == "选择 effort")
    assert effort_prompt[1] == ["low", "medium", "high", "xhigh (Extra high)"]
    assert effort_prompt[2] == "high"
    assert not any("不支持之前的 effort" in notice for notice in notices)
    assert route.provider == "codex_official"
    assert route.effort == "high"
