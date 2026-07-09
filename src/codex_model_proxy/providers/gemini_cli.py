from __future__ import annotations

import os

from .base import ProviderModel, ProviderSpec


DEFAULT_GEMINI_MODEL = "gemini-3-pro"
DEFAULT_GEMINI_MODELS = ",".join(
    [
        "gemini-3-pro",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]
)


class GeminiCliProviderFactory:
    backend_id = "gemini_cli"

    def from_env(self) -> ProviderSpec:
        return ProviderSpec(
            backend_id=self.backend_id,
            route_prefix="gemini",
            display_name=os.getenv("GEMINI_PROXY_DISPLAY_NAME", "Gemini"),
            default_model=os.getenv("GEMINI_DEFAULT_MODEL", DEFAULT_GEMINI_MODEL),
            models=self._models_from_env(),
            owned_by="google-gemini-cli",
            catalog_description="Gemini model accessed through the local gemini CLI proxy.",
            comp_hash="gemini-cli-proxy-v1",
            runner_description="local gemini CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("GEMINI_MODELS", DEFAULT_GEMINI_MODELS)
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_GEMINI_MODEL]
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
            "gemini-3-pro": ("gemini", "gemini-pro", "pro"),
            "gemini-2.5-pro": ("gemini-2.5", "gemini-2.5-pro-latest"),
            "gemini-2.5-flash": ("gemini-flash", "flash"),
        }
        return aliases.get(name, ())
