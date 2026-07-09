from __future__ import annotations

import os

from .base import ProviderModel, ProviderSpec


DEFAULT_CURSOR_MODEL = "auto"
DEFAULT_CURSOR_MODELS = ",".join(
    [
        "auto",
        "composer-2.5",
        "grok-4.5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "gpt-5.5",
        "gemini-3-1-pro",
    ]
)


class CursorAgentProviderFactory:
    backend_id = "cursor_agent"

    def from_env(self) -> ProviderSpec:
        return ProviderSpec(
            backend_id=self.backend_id,
            route_prefix="cursor",
            display_name=os.getenv("CURSOR_PROXY_DISPLAY_NAME", "Cursor"),
            default_model=os.getenv("CURSOR_DEFAULT_MODEL", DEFAULT_CURSOR_MODEL),
            models=self._models_from_env(),
            owned_by="cursor-agent-cli",
            catalog_description="Cursor model accessed through the local Cursor Agent CLI proxy.",
            comp_hash="cursor-agent-proxy-v1",
            runner_description="local Cursor Agent CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("CURSOR_MODELS", DEFAULT_CURSOR_MODELS)
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_CURSOR_MODEL]
        return tuple(
            ProviderModel(
                slug=name,
                display_name=self._display_name(name),
                aliases=self._aliases_for(name),
            )
            for name in names
        )

    @staticmethod
    def _display_name(name: str) -> str:
        if name == "auto":
            return "Auto"
        return name.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _aliases_for(name: str) -> tuple[str, ...]:
        aliases: dict[str, tuple[str, ...]] = {
            "auto": ("cursor-auto",),
            "composer-2.5": ("composer", "cursor-composer"),
            "grok-4.5": ("cursor-grok",),
            "claude-opus-4-8": ("cursor-opus",),
            "claude-sonnet-5": ("cursor-sonnet",),
            "gpt-5.5": ("cursor-gpt",),
            "gemini-3-1-pro": ("cursor-gemini",),
        }
        return aliases.get(name, ())
