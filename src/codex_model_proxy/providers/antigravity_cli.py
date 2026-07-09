from __future__ import annotations

import os

from .base import ProviderModel, ProviderSpec


DEFAULT_ANTIGRAVITY_MODEL = "gemini-3-pro"
DEFAULT_ANTIGRAVITY_MODELS = ",".join(
    [
        "gemini-3-pro",
        "gemini-3-flash",
        "gemini-3-1-pro",
    ]
)


class AntigravityCliProviderFactory:
    backend_id = "antigravity_cli"

    def from_env(self) -> ProviderSpec:
        return ProviderSpec(
            backend_id=self.backend_id,
            route_prefix="antigravity",
            display_name=os.getenv("ANTIGRAVITY_PROXY_DISPLAY_NAME", "Antigravity"),
            default_model=os.getenv("ANTIGRAVITY_DEFAULT_MODEL", DEFAULT_ANTIGRAVITY_MODEL),
            models=self._models_from_env(),
            owned_by="google-antigravity-cli",
            catalog_description="Gemini model accessed through the local Antigravity CLI proxy.",
            comp_hash="antigravity-cli-proxy-v1",
            runner_description="local Antigravity CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("ANTIGRAVITY_MODELS", DEFAULT_ANTIGRAVITY_MODELS)
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_ANTIGRAVITY_MODEL]
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
        return name.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _aliases_for(name: str) -> tuple[str, ...]:
        aliases: dict[str, tuple[str, ...]] = {
            "gemini-3-pro": ("antigravity-gemini", "antigravity-pro"),
            "gemini-3-flash": ("antigravity-flash",),
            "gemini-3-1-pro": ("antigravity-gemini-3-1",),
        }
        return aliases.get(name, ())
