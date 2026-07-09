from __future__ import annotations

import os

from .base import ProviderModel, ProviderSpec


DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_CLAUDE_MODELS = ",".join(
    [
        "fable",
        "opus",
        "sonnet",
        "haiku",
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",
    ]
)


class ClaudeCodeProviderFactory:
    backend_id = "claude_code"

    def from_env(self) -> ProviderSpec:
        models = self._models_from_env()
        return ProviderSpec(
            backend_id=self.backend_id,
            route_prefix="claude",
            display_name=os.getenv("MODEL_PROXY_DISPLAY_NAME", "Claude"),
            default_model=os.getenv(
                "CLAUDE_DEFAULT_MODEL",
                DEFAULT_CLAUDE_MODEL,
            ),
            models=models,
            owned_by="anthropic-claude-code-cli",
            catalog_description="Claude Code model accessed through the local claude CLI proxy.",
            comp_hash="claude-code-cli-proxy-v1",
            runner_description="local claude CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("CLAUDE_MODELS", DEFAULT_CLAUDE_MODELS)
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_CLAUDE_MODEL]
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
        return name.replace("-", " ").replace("_", " ").title().replace("Cli", "CLI")

    @staticmethod
    def _aliases_for(name: str) -> tuple[str, ...]:
        aliases: dict[str, tuple[str, ...]] = {
            "claude-fable-5": ("fable-latest",),
            "claude-opus-4-8": ("opus-latest",),
            "claude-sonnet-5": ("sonnet-latest",),
            "claude-haiku-4-5": ("haiku-latest",),
        }
        return aliases.get(name, ())
