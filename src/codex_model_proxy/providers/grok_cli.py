from __future__ import annotations

import os

from .base import ProviderModel, ProviderSpec


DEFAULT_GROK_MODEL = "grok-4.5"
DEFAULT_GROK_MODELS = ",".join(["grok-4.5"])


class GrokCliProviderFactory:
    backend_id = "grok_cli"

    def from_env(self) -> ProviderSpec:
        return ProviderSpec(
            backend_id=self.backend_id,
            route_prefix="grok",
            display_name=os.getenv("GROK_PROXY_DISPLAY_NAME", "Grok"),
            default_model=os.getenv("GROK_DEFAULT_MODEL", DEFAULT_GROK_MODEL),
            models=self._models_from_env(),
            owned_by="xai-grok-cli",
            catalog_description="Grok model accessed through the local Grok CLI proxy.",
            comp_hash="grok-cli-proxy-v1",
            runner_description="local Grok CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("GROK_MODELS", DEFAULT_GROK_MODELS)
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_GROK_MODEL]
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
            "grok-4.5": ("grok-latest", "xai"),
        }
        return aliases.get(name, ())
