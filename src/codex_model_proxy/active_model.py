from __future__ import annotations

from pathlib import Path

from .providers.claude_code import DEFAULT_CLAUDE_MODEL, DEFAULT_CLAUDE_MODELS, STABLE_CLAUDE_MODEL
from .providers.base import ProviderSpec


DEFAULT_MODEL = DEFAULT_CLAUDE_MODEL
STABLE_MODEL = STABLE_CLAUDE_MODEL


class ActiveModelStore:
    def __init__(
        self,
        path: str | Path | None = None,
        default_model: str | None = None,
        available_models: list[str] | None = None,
        stable_model: str = STABLE_MODEL,
        provider: ProviderSpec | None = None,
    ) -> None:
        if provider is not None:
            path = path or provider.active_model_file
            default_model = default_model or provider.default_model
            available_models = available_models or provider.available_model_ids
            stable_model = provider.stable_model

        self.path = Path(path or "~/.codex/model-proxy-active-model").expanduser()
        self.default_model = default_model or DEFAULT_MODEL
        self.available_models = available_models or [
            model.strip()
            for model in DEFAULT_CLAUDE_MODELS.split(",")
            if model.strip()
        ]
        self.stable_model = stable_model

    def get(self) -> str:
        try:
            model = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return self.default_model
        if not model:
            return self.default_model
        if model not in self.available_models:
            return self.default_model
        return model

    def set(self, model: str) -> str:
        model = model.strip()
        if model == self.stable_model:
            model = self.default_model
        if model not in self.available_models:
            allowed = ", ".join(self.available_models)
            raise ValueError(f"Unknown model '{model}'. Expected one of: {allowed}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(model + "\n", encoding="utf-8")
        temp_path.replace(self.path)
        return model
