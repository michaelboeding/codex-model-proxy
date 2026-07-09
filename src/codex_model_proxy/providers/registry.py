from __future__ import annotations

import os
from collections.abc import Callable

from .base import ModelRoute, ProviderSpec
from .antigravity_cli import AntigravityCliProviderFactory
from .claude_code import ClaudeCodeProviderFactory
from .cursor_agent import CursorAgentProviderFactory
from .gemini_cli import GeminiCliProviderFactory
from .grok_cli import GrokCliProviderFactory
from .openai_codex_cli import OpenAICodexCliProviderFactory


class ProviderRegistry:
    def __init__(self, factories: dict[str, Callable[[], ProviderSpec]] | None = None) -> None:
        self._factories = factories or {
            ClaudeCodeProviderFactory.backend_id: ClaudeCodeProviderFactory().from_env,
            OpenAICodexCliProviderFactory.backend_id: OpenAICodexCliProviderFactory().from_env,
            GeminiCliProviderFactory.backend_id: GeminiCliProviderFactory().from_env,
            AntigravityCliProviderFactory.backend_id: AntigravityCliProviderFactory().from_env,
            GrokCliProviderFactory.backend_id: GrokCliProviderFactory().from_env,
            CursorAgentProviderFactory.backend_id: CursorAgentProviderFactory().from_env,
        }
        self.stable_model = os.getenv("MODEL_PROXY_STABLE_MODEL", os.getenv("CLAUDE_STABLE_MODEL", "claude"))
        self.codex_provider_id = os.getenv("MODEL_PROXY_PROVIDER_ID", "claude_code_cli_proxy")
        self.display_name = os.getenv("MODEL_PROXY_DISPLAY_NAME", "Model Proxy")
        self._providers = self._load_providers()
        self._routes = self._build_routes()
        self._aliases = self._build_aliases()
        self.default_route_id = self._default_route_id()

    @property
    def providers(self) -> tuple[ProviderSpec, ...]:
        return tuple(self._providers.values())

    @property
    def route_ids(self) -> list[str]:
        return list(self._routes.keys())

    @property
    def catalog_model_ids(self) -> list[str]:
        names = [self.stable_model]
        names.extend(route_id for route_id in self.route_ids if route_id not in names)
        return names

    @property
    def accepted_model_ids(self) -> list[str]:
        names = list(self.catalog_model_ids)
        for alias in sorted(self._aliases):
            if alias not in names:
                names.append(alias)
        return names

    def route(self, route_id: str) -> ModelRoute:
        try:
            return self._routes[route_id]
        except KeyError as exc:
            raise ValueError(self._unknown_model_message(route_id)) from exc

    def resolve_route_id(self, requested_model: object) -> str:
        requested = str(requested_model or "").strip()
        if not requested:
            return self.default_route_id
        if requested == self.stable_model:
            return getattr(self, "default_route_id", next(iter(self._routes)))
        resolved = self._aliases.get(requested)
        if resolved:
            return resolved
        raise ValueError(self._unknown_model_message(requested))

    def resolve_request_model(self, requested_model: object, active_route_id: str) -> str:
        requested = str(requested_model or "").strip()
        if not requested or requested == self.stable_model:
            return self.resolve_route_id(active_route_id)
        try:
            return self.resolve_route_id(requested)
        except ValueError:
            return self.resolve_route_id(active_route_id)

    def display_name_for(self, model_id: str) -> str:
        if model_id == self.stable_model:
            return self.display_name
        route = self._routes.get(model_id)
        if route:
            return route.display_name
        return model_id.replace(":", " ").replace("-", " ").replace("_", " ").title()

    def model_catalog(self) -> list[dict[str, object]]:
        return [
            {
                "id": route.route_id,
                "provider": route.provider.backend_id,
                "provider_display_name": route.provider.display_name,
                "model": route.model,
                "display_name": route.display_name,
                "aliases": [
                    alias
                    for alias, route_id in sorted(self._aliases.items())
                    if route_id == route.route_id and alias != route.route_id
                ],
                "runner": route.provider.runner_description,
                "requires_auth_env": list(route.provider.requires_auth_env),
            }
            for route in self._routes.values()
        ]

    def _load_providers(self) -> dict[str, ProviderSpec]:
        enabled = self._enabled_provider_ids()
        providers: dict[str, ProviderSpec] = {}
        for backend_id, factory in self._factories.items():
            if enabled and backend_id not in enabled:
                continue
            providers[backend_id] = factory()
        if not providers:
            available = ", ".join(sorted(self._factories))
            raise ValueError(f"No model proxy providers enabled. Available backends: {available}")
        return providers

    def _enabled_provider_ids(self) -> set[str]:
        configured = os.getenv("MODEL_PROXY_ENABLED_PROVIDERS")
        if not configured:
            return set()
        enabled = {name.strip() for name in configured.split(",") if name.strip()}
        unknown = enabled.difference(self._factories)
        if unknown:
            available = ", ".join(sorted(self._factories))
            raise ValueError(
                f"Unknown model proxy providers: {', '.join(sorted(unknown))}. "
                f"Available backends: {available}"
            )
        return enabled

    def _build_routes(self) -> dict[str, ModelRoute]:
        routes: dict[str, ModelRoute] = {}
        for provider in self._providers.values():
            for model in provider.models:
                route_id = provider.route_id(model.slug)
                routes[route_id] = ModelRoute(route_id=route_id, provider=provider, model=model.slug)
        return routes

    def _build_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for route_id in self._routes:
            aliases[route_id] = route_id
        for provider in self._providers.values():
            default_route = provider.route_id(provider.default_model)
            if default_route in self._routes and provider.route_prefix != self.stable_model:
                aliases[provider.route_prefix] = default_route
            for model_slug, resolved_slug in provider.aliases.items():
                route_id = provider.route_id(resolved_slug)
                if route_id not in self._routes:
                    continue
                aliases.setdefault(model_slug, route_id)
                aliases.setdefault(provider.route_id(model_slug), route_id)
        return aliases

    def _default_route_id(self) -> str:
        configured_model = os.getenv("MODEL_PROXY_DEFAULT_MODEL")
        if configured_model:
            configured = configured_model.strip()
            if configured and configured != self.stable_model:
                return self.resolve_route_id(configured)

        backend_id = os.getenv("MODEL_PROXY_BACKEND", os.getenv("LOCAL_MODEL_PROVIDER", "claude_code"))
        provider = self._providers.get(backend_id) or next(iter(self._providers.values()))
        default_route = provider.route_id(provider.default_model)
        if default_route in self._routes:
            return default_route
        return next(iter(self._routes))

    def _unknown_model_message(self, requested: str) -> str:
        allowed = ", ".join(self.accepted_model_ids)
        return f"Unknown model '{requested}'. Expected one of: {allowed}"


def selected_provider() -> ProviderSpec:
    registry = ProviderRegistry()
    return registry.route(registry.default_route_id).provider
