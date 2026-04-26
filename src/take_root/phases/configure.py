from __future__ import annotations

from pathlib import Path

from take_root.config import (
    EFFORT_VALUES_BY_KIND,
    PERSONA_NAMES,
    ActorRouteConfig,
    ProviderConfig,
    TakeRootConfig,
    config_exists,
    default_take_root_config,
    load_config,
    save_config,
)
from take_root.errors import ConfigError
from take_root.ui import ask, info, select_option

SECTION_CHOICES = {"providers", "init", "personas"}
CODEX_MODEL_CHOICES = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
]
QWEN_MODEL_CHOICES = ["qwen3-max", "qwen3.6-plus", "qwen3.5-flash"]
KIMI_MODEL_CHOICES = ["kimi-k2.6"]
DEEPSEEK_MODEL_CHOICES = ["deepseek-v4-pro[1m]", "deepseek-v4-flash"]
BUILTIN_COMPATIBLE_PROVIDERS = ("qwen", "kimi", "deepseek")
BUILTIN_MODEL_CHOICES = {
    "qwen": QWEN_MODEL_CHOICES,
    "kimi": KIMI_MODEL_CHOICES,
    "deepseek": DEEPSEEK_MODEL_CHOICES,
}
EFFORT_DISPLAY_LABELS = {"xhigh": "xhigh (Extra high)"}


def _select_option(prompt: str, options: list[str], default: str) -> str:
    return select_option(prompt, options, default)


def _with_current_option(options: list[str], current: str) -> list[str]:
    if current in options:
        return options
    return [current, *options]


def _supported_provider_names(provider_names: list[str], *, allow_codex: bool) -> list[str]:
    if allow_codex:
        return provider_names
    return [name for name in provider_names if name != "codex_official"]


def _supported_model_text(provider_name: str, provider: ProviderConfig) -> str:
    defaults = provider.default_models or {}
    if provider_name == "codex_official":
        return "/".join(CODEX_MODEL_CHOICES) + " 或其他具体模型名"
    if defaults:
        mapped = ", ".join(
            f"{alias}->{model}" for alias, model in defaults.items() if model.strip()
        )
        if mapped:
            return f"opus/sonnet/haiku 或具体模型名（当前映射: {mapped}）"
    return "opus/sonnet/haiku 或具体模型名"


def _default_model_for_provider(provider_name: str, provider: ProviderConfig) -> str:
    defaults = provider.default_models or {}
    if provider_name == "codex_official":
        return defaults.get("opus", "gpt-5.5")
    if provider_name == "claude_official":
        return "opus"
    if defaults:
        return "sonnet"
    return ""


def _display_effort(effort: str) -> str:
    return EFFORT_DISPLAY_LABELS.get(effort, effort)


def _effort_options_for_provider(provider: ProviderConfig) -> tuple[str, ...]:
    return EFFORT_VALUES_BY_KIND[provider.kind]


def _prompt_effort(
    route: ActorRouteConfig,
    provider_name: str,
    provider: ProviderConfig,
    *,
    provider_changed: bool,
) -> str:
    effort_options = _effort_options_for_provider(provider)
    if provider_changed and route.effort not in effort_options:
        info(f"{provider_name} 不支持之前的 effort，正在重新选择。")
    effort_default = route.effort if route.effort in effort_options else "medium"
    if effort_default not in effort_options:
        effort_default = effort_options[0]
    labels = [_display_effort(effort) for effort in effort_options]
    effort_by_label = dict(zip(labels, effort_options, strict=True))
    selected_label = _select_option("选择 effort", labels, _display_effort(effort_default))
    return effort_by_label[selected_label]


def _prompt_model(
    provider_name: str,
    *,
    model_hint: str,
    model_default: str,
) -> str:
    if provider_name == "codex_official":
        codex_default = (
            model_default if model_default in CODEX_MODEL_CHOICES else CODEX_MODEL_CHOICES[0]
        )
        return _select_option("选择 model", CODEX_MODEL_CHOICES, codex_default)
    if provider_name in BUILTIN_COMPATIBLE_PROVIDERS:
        model_options = ["opus", "sonnet", "haiku"]
        model_default_for_select = model_default if model_default in model_options else "sonnet"
        return _select_option(
            f"选择 model（{model_hint}）",
            model_options,
            model_default_for_select,
        )
    model_options = ["opus", "sonnet", "haiku", "(自定义)"]
    model_default_for_select = model_default if model_default in model_options[:-1] else "(自定义)"
    selected = _select_option(
        f"选择 model（{model_hint}，或输入自定义模型名）",
        model_options,
        model_default_for_select,
    )
    if selected != "(自定义)":
        return selected
    custom_default = model_default if model_default_for_select == "(自定义)" else ""
    return ask("输入具体模型名", default=custom_default)


def _prompt_api_key(name: str, provider: ProviderConfig) -> ProviderConfig:
    existing_hint = "直接回车保持已保存值" if provider.auth_token else "必须输入"
    while True:
        api_key = ask(f"{name} api_key（{existing_hint}）", default="")
        if api_key:
            auth_token = api_key
            break
        if provider.auth_token:
            auth_token = provider.auth_token
            break
        info("api_key 不能为空")
    return ProviderConfig(
        kind=provider.kind,
        base_url=provider.base_url,
        auth_token_env=provider.auth_token_env,
        auth_token=auth_token,
        default_models=provider.default_models,
    )


def _provider_prompt(name: str, provider: ProviderConfig) -> ProviderConfig:
    if name == "claude_official":
        info("[configure] claude_official 固定为本机 Claude 登录态")
        return ProviderConfig(kind="claude_official", default_models=provider.default_models)
    if name == "codex_official":
        info("[configure] codex_official 固定为本机 Codex 登录态")
        return ProviderConfig(kind="codex_official", default_models=provider.default_models)
    info(f"[configure] 配置 provider: {name}")
    defaults = provider.default_models or {}
    if name in BUILTIN_COMPATIBLE_PROVIDERS:
        configured_provider = _prompt_api_key(name, provider)
        model_choices = BUILTIN_MODEL_CHOICES[name]
        models = {
            alias: _select_option(
                f"选择 default_models.{alias}",
                _with_current_option(
                    model_choices,
                    defaults.get(alias, ""),
                ),
                defaults.get(alias, ""),
            )
            for alias in ("opus", "sonnet", "haiku")
        }
        return ProviderConfig(
            kind=configured_provider.kind,
            base_url=configured_provider.base_url,
            auth_token_env=configured_provider.auth_token_env,
            auth_token=configured_provider.auth_token,
            default_models=models,
        )
    base_url = ask("base_url（例如 https://example.com/v1）", default=provider.base_url or "")
    models = {
        alias: ask(
            f"default_models.{alias}（可填具体模型名）",
            default=defaults.get(alias, ""),
        )
        for alias in ("opus", "sonnet", "haiku")
    }
    custom_provider = ProviderConfig(
        kind="anthropic_compatible",
        base_url=base_url,
        auth_token_env=provider.auth_token_env,
        auth_token=provider.auth_token,
        default_models=models,
    )
    return _prompt_api_key(name, custom_provider)


def _prompt_custom_provider(current: dict[str, ProviderConfig]) -> dict[str, ProviderConfig]:
    updated = dict(current)
    enabled = _select_option(
        "是否配置 custom provider？",
        ["no", "yes"],
        "yes" if "custom" in current else "no",
    )
    if enabled == "yes":
        updated["custom"] = _provider_prompt(
            "custom",
            current.get("custom", ProviderConfig(kind="anthropic_compatible")),
        )
    else:
        updated.pop("custom", None)
    return updated


def _prompt_providers(config: TakeRootConfig) -> dict[str, ProviderConfig]:
    updated = dict(config.providers)
    defaults = default_take_root_config().providers
    updated["claude_official"] = _provider_prompt(
        "claude_official",
        updated.get("claude_official", ProviderConfig(kind="claude_official")),
    )
    updated["codex_official"] = _provider_prompt(
        "codex_official",
        updated.get("codex_official", defaults["codex_official"]),
    )
    for name in BUILTIN_COMPATIBLE_PROVIDERS:
        updated[name] = _provider_prompt(
            name,
            updated.get(name, defaults[name]),
        )
    return _prompt_custom_provider(updated)


def _merge_missing_builtin_providers(config: TakeRootConfig) -> TakeRootConfig:
    defaults = default_take_root_config()
    providers = {**defaults.providers, **config.providers}
    return TakeRootConfig(
        schema_version=config.schema_version,
        providers=providers,
        init=config.init,
        personas=config.personas,
    )


def _prompt_route(
    label: str,
    route: ActorRouteConfig,
    providers: dict[str, ProviderConfig],
    provider_names: list[str],
    *,
    allow_codex: bool,
) -> ActorRouteConfig:
    info(f"[configure] 配置 {label}")
    visible_provider_names = _supported_provider_names(
        provider_names,
        allow_codex=allow_codex,
    )
    provider_default = (
        route.provider if route.provider in visible_provider_names else visible_provider_names[0]
    )
    provider = _select_option("选择 provider", visible_provider_names, provider_default)
    selected_provider = providers.get(provider)
    model_hint = "opus/sonnet/haiku 或具体模型名"
    model_default = route.model
    if selected_provider is not None:
        model_hint = _supported_model_text(provider, selected_provider)
        if provider != route.provider:
            model_default = _default_model_for_provider(provider, selected_provider)
    model = _prompt_model(provider, model_hint=model_hint, model_default=model_default)
    if selected_provider is None:
        raise ConfigError(f"未找到 provider: {provider}")
    effort = _prompt_effort(
        route,
        provider,
        selected_provider,
        provider_changed=provider != route.provider,
    )
    return ActorRouteConfig(provider=provider, model=model, effort=effort)


def _prompt_init(
    config: TakeRootConfig,
    providers: dict[str, ProviderConfig],
) -> ActorRouteConfig:
    return _prompt_route("init", config.init, providers, list(providers), allow_codex=True)


def _prompt_personas(
    config: TakeRootConfig,
    providers: dict[str, ProviderConfig],
) -> dict[str, ActorRouteConfig]:
    updated = dict(config.personas)
    defaults = default_take_root_config().personas
    for name in PERSONA_NAMES:
        updated[name] = _prompt_route(
            name,
            updated.get(name, defaults[name]),
            providers,
            list(providers),
            allow_codex=True,
        )
    return updated


def run_configure(
    project_root: Path,
    *,
    reset: bool = False,
    section: str | None = None,
) -> TakeRootConfig:
    if section is not None and section not in SECTION_CHOICES:
        raise ConfigError(f"unknown section: {section}")
    if config_exists(project_root) and not reset:
        config = _merge_missing_builtin_providers(load_config(project_root))
    else:
        config = default_take_root_config()

    providers = dict(config.providers)
    init_route = config.init
    personas = dict(config.personas)

    if section in {None, "providers"}:
        providers = _prompt_providers(config)
    if section in {None, "init"}:
        init_route = _prompt_init(config, providers)
    if section in {None, "personas"}:
        personas = _prompt_personas(config, providers)

    updated = TakeRootConfig(
        schema_version=config.schema_version,
        providers=providers,
        init=init_route,
        personas=personas,
    )
    save_config(project_root, updated)
    info(f"已写入 {project_root / '.take_root' / 'config.yaml'}")
    return updated
