from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from take_root.artifacts import ensure_layout
from take_root.errors import ConfigError

CONFIG_SCHEMA_VERSION = 1
MODEL_ALIASES = ("opus", "sonnet", "haiku")
VALID_PROVIDER_KINDS = {"claude_official", "codex_official", "anthropic_compatible"}
VALID_EFFORTS = {"minimal", "low", "medium", "high"}
PERSONA_NAMES = ("jeff", "robin", "neo", "lucy", "peter", "amy")
ANTHROPIC_ENV_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)
CLAUDE_OFFICIAL_DEFAULT_MODELS = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}
CODEX_OFFICIAL_DEFAULT_MODELS = {
    "opus": "gpt-5.4",
    "sonnet": "gpt-5.4-mini",
    "haiku": "gpt-5.4-mini",
}
QWEN_DEFAULT_MODELS = {
    "opus": "qwen3-max",
    "sonnet": "qwen3.6-plus",
    "haiku": "qwen3.5-flash",
}
KIMI_DEFAULT_MODELS = {
    "opus": "kimi-k2.5",
    "sonnet": "kimi-k2.5",
    "haiku": "kimi-k2.5",
}


@dataclass(frozen=True)
class ProviderConfig:
    kind: str
    base_url: str | None = None
    auth_token_env: str | None = None
    auth_token: str | None = None
    default_models: dict[str, str] | None = None


@dataclass(frozen=True)
class ActorRouteConfig:
    provider: str
    model: str
    effort: str | None


@dataclass(frozen=True)
class TakeRootConfig:
    schema_version: int
    providers: dict[str, ProviderConfig]
    init: ActorRouteConfig
    personas: dict[str, ActorRouteConfig]


@dataclass(frozen=True)
class ResolvedRuntimeConfig:
    runtime_name: str
    provider_name: str
    provider_kind: str
    base_url: str | None
    model_selector: str
    resolved_model: str
    effort: str | None
    token_source: str
    env: dict[str, str]
    cleared_env_vars: tuple[str, ...]

    @property
    def env_was_cleaned(self) -> bool:
        return bool(self.cleared_env_vars)


def config_path(project_root: Path) -> Path:
    return project_root / ".take_root" / "config.yaml"


def default_take_root_config() -> TakeRootConfig:
    providers = {
        "claude_official": ProviderConfig(
            kind="claude_official",
            default_models=CLAUDE_OFFICIAL_DEFAULT_MODELS,
        ),
        "codex_official": ProviderConfig(
            kind="codex_official",
            default_models=CODEX_OFFICIAL_DEFAULT_MODELS,
        ),
        "qwen": ProviderConfig(
            kind="anthropic_compatible",
            base_url="https://dashscope.aliyuncs.com/apps/anthropic",
            auth_token_env="ANTHROPIC_AUTH_TOKEN_QWEN",
            default_models=QWEN_DEFAULT_MODELS,
        ),
        "kimi": ProviderConfig(
            kind="anthropic_compatible",
            base_url="https://api.moonshot.cn/anthropic",
            auth_token_env="ANTHROPIC_AUTH_TOKEN_KIMI",
            default_models=KIMI_DEFAULT_MODELS,
        ),
    }
    personas = {
        "jeff": ActorRouteConfig(provider="qwen", model="sonnet", effort="medium"),
        "robin": ActorRouteConfig(provider="qwen", model="opus", effort="high"),
        "neo": ActorRouteConfig(provider="kimi", model="sonnet", effort="high"),
        "lucy": ActorRouteConfig(provider="codex_official", model="opus", effort="high"),
        "peter": ActorRouteConfig(provider="codex_official", model="opus", effort="high"),
        "amy": ActorRouteConfig(provider="codex_official", model="sonnet", effort="medium"),
    }
    return TakeRootConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        providers=providers,
        init=ActorRouteConfig(provider="claude_official", model="opus", effort="medium"),
        personas=personas,
    )


def config_exists(project_root: Path) -> bool:
    return config_path(project_root).exists()


def require_config(project_root: Path) -> TakeRootConfig:
    if not config_exists(project_root):
        raise ConfigError("未检测到 .take_root/config.yaml，请先执行 `take-root configure`")
    return load_config(project_root)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} 必须是对象")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} 必须是非空字符串")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label)


def _normalize_default_models(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    mapping = _require_mapping(value, label)
    models: dict[str, str] = {}
    for alias, model in mapping.items():
        alias_name = _require_string(alias, f"{label} alias")
        if alias_name not in MODEL_ALIASES:
            raise ConfigError(f"{label} 包含未知 alias: {alias_name}")
        models[alias_name] = _require_string(model, f"{label}.{alias_name}")
    return models


def _load_provider(name: str, raw: Any) -> ProviderConfig:
    data = _require_mapping(raw, f"providers.{name}")
    kind = _require_string(data.get("kind"), f"providers.{name}.kind")
    if kind not in VALID_PROVIDER_KINDS:
        raise ConfigError(f"providers.{name}.kind 不支持: {kind}")
    default_models = _normalize_default_models(
        data.get("default_models"), f"providers.{name}.default_models"
    )
    builtin_defaults = default_take_root_config().providers.get(name)
    builtin_default_models = (
        builtin_defaults.default_models if builtin_defaults is not None else None
    )
    if kind in {"claude_official", "codex_official"}:
        return ProviderConfig(
            kind=kind,
            default_models=default_models or builtin_default_models,
        )
    base_url = _require_string(data.get("base_url"), f"providers.{name}.base_url")
    auth_token_env = _optional_string(
        data.get("auth_token_env"), f"providers.{name}.auth_token_env"
    )
    auth_token = _optional_string(data.get("auth_token"), f"providers.{name}.auth_token")
    if auth_token_env is None and auth_token is None:
        raise ConfigError(f"providers.{name} 需要 auth_token 或 auth_token_env")
    return ProviderConfig(
        kind=kind,
        base_url=base_url,
        auth_token_env=auth_token_env,
        auth_token=auth_token,
        default_models=default_models or builtin_default_models,
    )


def _load_actor_route(raw: Any, label: str) -> ActorRouteConfig:
    data = _require_mapping(raw, label)
    provider = _require_string(data.get("provider"), f"{label}.provider")
    model = _require_string(data.get("model"), f"{label}.model")
    effort = _optional_string(data.get("effort"), f"{label}.effort")
    if effort is not None and effort not in VALID_EFFORTS:
        raise ConfigError(f"{label}.effort 不支持: {effort}")
    return ActorRouteConfig(provider=provider, model=model, effort=effort)


def load_config(project_root: Path) -> TakeRootConfig:
    path = config_path(project_root)
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = _require_mapping(raw, "config.yaml")
    version = data.get("schema_version")
    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"不支持的 config schema_version: {version}，期望 {CONFIG_SCHEMA_VERSION}"
        )
    raw_providers = _require_mapping(data.get("providers"), "providers")
    providers = {name: _load_provider(name, value) for name, value in raw_providers.items()}
    init_config = _load_actor_route(data.get("init"), "init")
    raw_personas = _require_mapping(data.get("personas"), "personas")
    personas = {
        name: _load_actor_route(value, f"personas.{name}") for name, value in raw_personas.items()
    }
    return TakeRootConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        providers=providers,
        init=init_config,
        personas=personas,
    )


def _provider_to_dict(provider: ProviderConfig) -> dict[str, Any]:
    data: dict[str, Any] = {"kind": provider.kind}
    if provider.base_url is not None:
        data["base_url"] = provider.base_url
    if provider.auth_token_env is not None:
        data["auth_token_env"] = provider.auth_token_env
    if provider.auth_token is not None:
        data["auth_token"] = provider.auth_token
    if provider.default_models:
        data["default_models"] = dict(provider.default_models)
    return data


def _actor_to_dict(route: ActorRouteConfig) -> dict[str, Any]:
    data: dict[str, Any] = {
        "provider": route.provider,
        "model": route.model,
    }
    if route.effort is not None:
        data["effort"] = route.effort
    return data


def save_config(project_root: Path, config: TakeRootConfig) -> None:
    ensure_layout(project_root)
    payload = {
        "schema_version": config.schema_version,
        "providers": {
            name: _provider_to_dict(provider) for name, provider in config.providers.items()
        },
        "init": _actor_to_dict(config.init),
        "personas": {name: _actor_to_dict(route) for name, route in config.personas.items()},
    }
    path = config_path(project_root)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def _resolve_actor_route(
    *,
    config: TakeRootConfig,
    route: ActorRouteConfig,
    label: str,
) -> ResolvedRuntimeConfig:
    provider = config.providers.get(route.provider)
    if provider is None:
        raise ConfigError(f"{label} 指向了不存在的 provider: {route.provider}")
    if provider.kind not in VALID_PROVIDER_KINDS:
        raise ConfigError(f"{label} 使用了未知 provider 类型: {provider.kind}")
    selector = route.model
    resolved_model = selector
    if selector in MODEL_ALIASES:
        defaults = provider.default_models or {}
        resolved_model = defaults.get(selector, "")
        if not resolved_model:
            raise ConfigError(f"{label} 的 model alias 无法解析: {selector}")
    if route.provider == "kimi" and resolved_model != "kimi-k2.5":
        raise ConfigError(f"{label} 的 kimi 仅支持 kimi-k2.5，当前为: {resolved_model}")
    runtime_name = "claude"
    if provider.kind == "codex_official":
        runtime_name = "codex"
    env: dict[str, str] = {}
    token_source = "cli-login"
    if provider.kind == "anthropic_compatible":
        base_url = _require_string(provider.base_url, f"{label}.provider.base_url")
        token = provider.auth_token
        token_env_name = provider.auth_token_env
        if token:
            token_source = f"config:providers.{route.provider}.auth_token"
        elif token_env_name:
            token = os.getenv(token_env_name)
            if not token:
                raise ConfigError(f"{label} 需要环境变量 {token_env_name}，当前未设置")
            token_source = f"env:{token_env_name}"
        else:
            raise ConfigError(f"{label} 缺少 API key 配置")
        env = {
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_AUTH_TOKEN": token,
            "ANTHROPIC_MODEL": resolved_model,
        }
        defaults = provider.default_models or {}
        for alias in MODEL_ALIASES:
            model_name = defaults.get(alias)
            if model_name:
                env[f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL"] = model_name
    return ResolvedRuntimeConfig(
        runtime_name=runtime_name,
        provider_name=route.provider,
        provider_kind=provider.kind,
        base_url=provider.base_url,
        model_selector=selector,
        resolved_model=resolved_model,
        effort=route.effort,
        token_source=token_source,
        env=env,
        cleared_env_vars=ANTHROPIC_ENV_KEYS,
    )


def resolve_init_runtime_config(config: TakeRootConfig) -> ResolvedRuntimeConfig:
    return _resolve_actor_route(config=config, route=config.init, label="init")


def resolve_persona_runtime_config(
    config: TakeRootConfig, persona_name: str
) -> ResolvedRuntimeConfig:
    route = config.personas.get(persona_name)
    if route is None:
        raise ConfigError(f"personas.{persona_name} 缺少 provider/model 配置")
    return _resolve_actor_route(
        config=config,
        route=route,
        label=f"personas.{persona_name}",
    )


def build_claude_env(config: TakeRootConfig, persona_name: str) -> dict[str, str]:
    return dict(resolve_persona_runtime_config(config, persona_name).env)


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def masked_runtime_env_summary(resolved: ResolvedRuntimeConfig) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in resolved.env.items():
        if "TOKEN" in key or "KEY" in key:
            masked[key] = mask_secret(value)
        else:
            masked[key] = value
    return masked


def masked_provider_summary(provider: ProviderConfig) -> dict[str, str]:
    summary: dict[str, str] = {}
    if provider.auth_token_env is not None:
        summary["auth_token_env"] = provider.auth_token_env
    if provider.auth_token is not None:
        summary["auth_token"] = mask_secret(provider.auth_token)
    return summary
