from __future__ import annotations

import os
from pathlib import Path

from .providers.base import ModelRoute
from .providers.registry import ProviderRegistry


class ActiveModelStore:
    def __init__(
        self,
        path: str | Path | None = None,
        default_model: str | None = None,
        available_models: list[str] | None = None,
        stable_model: str | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.path = Path(path or self._active_model_file()).expanduser()
        self.default_model = self.registry.resolve_route_id(default_model) if default_model else self.registry.default_route_id
        self.available_models = available_models or self.registry.accepted_model_ids
        self.stable_model = stable_model or self.registry.stable_model

    def get(self) -> str:
        try:
            model = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return self.default_model
        if not model:
            return self.default_model
        try:
            return self.registry.resolve_route_id(model)
        except ValueError:
            return self.default_model

    def get_route(self) -> ModelRoute:
        return self.registry.route(self.get())

    def set(self, model: str) -> str:
        model = model.strip()
        if model == self.stable_model:
            model = self.default_model
        route_id = self.registry.resolve_route_id(model)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(route_id + "\n", encoding="utf-8")
        temp_path.replace(self.path)
        return route_id

    @staticmethod
    def _active_model_file() -> Path:
        configured = os.getenv("MODEL_PROXY_ACTIVE_MODEL_FILE")
        if configured:
            return Path(configured).expanduser()
        return Path("~/.codex/model-proxy-active-model").expanduser()
