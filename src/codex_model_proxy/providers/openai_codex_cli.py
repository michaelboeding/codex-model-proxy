from __future__ import annotations

import os

from .base import ProviderModel, ProviderSpec


DEFAULT_OPENAI_CODEX_MODEL = "gpt-5.5"
DEFAULT_OPENAI_CODEX_MODELS = ",".join(
    [
        "gpt-5.5",
        "gpt-5.4-mini",
        "gpt-5.3-codex-spark",
    ]
)


class OpenAICodexCliProviderFactory:
    backend_id = "openai_codex_cli"

    def from_env(self) -> ProviderSpec:
        return ProviderSpec(
            backend_id=self.backend_id,
            route_prefix="openai",
            display_name=os.getenv("OPENAI_CODEX_PROXY_DISPLAY_NAME", "OpenAI"),
            default_model=os.getenv("OPENAI_CODEX_DEFAULT_MODEL", DEFAULT_OPENAI_CODEX_MODEL),
            models=self._models_from_env(),
            owned_by="openai-codex-cli",
            catalog_description="OpenAI model accessed through the local Codex CLI proxy.",
            comp_hash="openai-codex-cli-proxy-v1",
            runner_description="local codex CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("OPENAI_CODEX_MODELS", DEFAULT_OPENAI_CODEX_MODELS)
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_OPENAI_CODEX_MODEL]
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
        return name.replace("-", " ").replace("_", " ").upper().replace("GPT", "GPT")

    @staticmethod
    def _aliases_for(name: str) -> tuple[str, ...]:
        aliases: dict[str, tuple[str, ...]] = {
            "gpt-5.5": ("gpt", "gpt-latest", "openai", "chatgpt"),
            "gpt-5.4-mini": ("gpt-mini", "mini"),
            "gpt-5.3-codex-spark": ("spark", "codex-spark"),
        }
        return aliases.get(name, ())
