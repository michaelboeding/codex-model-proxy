from __future__ import annotations

from typing import Any, Protocol

from .antigravity_cli import AntigravityCliClient
from .claude_cli import ClaudeCliClient
from .cursor_agent import CursorAgentClient
from .errors import ModelBackendError
from .gemini_cli import GeminiCliClient
from .grok_cli import GrokCliClient
from .openai_codex_cli import OpenAICodexCliClient
from .providers.registry import ProviderRegistry


class CompletionResult(Protocol):
    text: str
    usage: dict[str, Any]


class BackendClient(Protocol):
    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> CompletionResult:
        ...


class RoutedModelClient:
    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        clients: dict[str, BackendClient] | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.clients = clients or {
            "claude_code": ClaudeCliClient(),
            "openai_codex_cli": OpenAICodexCliClient(),
            "gemini_cli": GeminiCliClient(),
            "antigravity_cli": AntigravityCliClient(),
            "grok_cli": GrokCliClient(),
            "cursor_agent": CursorAgentClient(),
        }

    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> CompletionResult:
        route = self.registry.route(model)
        client = self.clients.get(route.provider.backend_id)
        if client is None:
            available = ", ".join(sorted(self.clients))
            raise ModelBackendError(
                f"No model runner configured for backend provider '{route.provider.backend_id}'. "
                f"Available runners: {available}"
            )
        return client.complete(
            prompt,
            route.model,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
            effort=effort,
        )
