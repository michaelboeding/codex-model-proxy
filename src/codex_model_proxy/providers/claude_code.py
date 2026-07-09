from __future__ import annotations

import os
from pathlib import Path

from .base import ProviderModel, ProviderSpec


DEFAULT_CLAUDE_MODEL = "opus"
STABLE_CLAUDE_MODEL = "claude"
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
            codex_provider_id=os.getenv("MODEL_PROXY_PROVIDER_ID", "claude_code_cli_proxy"),
            display_name=os.getenv("MODEL_PROXY_DISPLAY_NAME", "Claude"),
            stable_model=os.getenv("MODEL_PROXY_STABLE_MODEL", os.getenv("CLAUDE_STABLE_MODEL", STABLE_CLAUDE_MODEL)),
            default_model=os.getenv(
                "MODEL_PROXY_DEFAULT_MODEL",
                os.getenv("CLAUDE_DEFAULT_MODEL", DEFAULT_CLAUDE_MODEL),
            ),
            models=models,
            active_model_file=self._active_model_file(),
            owned_by="anthropic-claude-code-cli",
            catalog_description="Claude Code model accessed through the local claude CLI proxy.",
            comp_hash="claude-code-cli-proxy-v1",
            runner_description="local claude CLI",
        )

    def _models_from_env(self) -> tuple[ProviderModel, ...]:
        raw_names = os.getenv("MODEL_PROXY_MODELS", os.getenv("CLAUDE_MODELS", DEFAULT_CLAUDE_MODELS))
        names = [name.strip() for name in raw_names.split(",") if name.strip()]
        if not names:
            names = [DEFAULT_CLAUDE_MODEL]
        return tuple(ProviderModel(slug=name, display_name=self._display_name(name)) for name in names)

    @staticmethod
    def _display_name(name: str) -> str:
        return name.replace("-", " ").replace("_", " ").title().replace("Cli", "CLI")

    @staticmethod
    def _active_model_file() -> Path:
        configured = os.getenv("MODEL_PROXY_ACTIVE_MODEL_FILE") or os.getenv("CLAUDE_ACTIVE_MODEL_FILE")
        if configured:
            return Path(configured).expanduser()

        old_path = Path("~/.codex/claude-proxy-active-model").expanduser()
        if old_path.exists():
            return old_path
        return Path("~/.codex/model-proxy-active-model").expanduser()
