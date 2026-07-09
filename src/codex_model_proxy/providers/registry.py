from __future__ import annotations

import os
from collections.abc import Callable

from .base import ProviderSpec
from .claude_code import ClaudeCodeProviderFactory


class ProviderRegistry:
    def __init__(self, factories: dict[str, Callable[[], ProviderSpec]] | None = None) -> None:
        self._factories = factories or {
            ClaudeCodeProviderFactory.backend_id: ClaudeCodeProviderFactory().from_env,
        }

    def selected(self) -> ProviderSpec:
        backend_id = os.getenv("MODEL_PROXY_BACKEND", os.getenv("LOCAL_MODEL_PROVIDER", "claude_code"))
        factory = self._factories.get(backend_id)
        if factory is None:
            available = ", ".join(sorted(self._factories))
            raise ValueError(f"Unknown model proxy backend '{backend_id}'. Available backends: {available}")
        return factory()


def selected_provider() -> ProviderSpec:
    return ProviderRegistry().selected()
