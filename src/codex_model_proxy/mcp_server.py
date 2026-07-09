from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, TextIO

from . import __version__
from .proxy_control import ModelProxyController, ModelProxyError


SERVER_NAME = "model-proxy-control"
INSTRUCTIONS = (
    "Use this server to inspect and control the local model proxy. "
    "The `switch_model` tool changes the backend model used for the next request "
    "behind the stable Codex-facing model; it does not change Codex's configured provider. "
    "Use qualified routes like `claude:opus`, `openai:gpt-5.5`, `gemini:gemini-3-pro`, "
    "`antigravity:gemini-3-pro`, `grok:grok-4.5`, or `cursor:auto`, "
    "or aliases such as `opus`, `gpt`, `gemini`, `antigravity`, `grok`, and `cursor`. "
    "Set MODEL_PROXY_AUTOSTART=1 to start the HTTP proxy automatically when this MCP server starts."
)


class ModelProxyMcpServer:
    def __init__(
        self,
        controller: ModelProxyController | None = None,
        *,
        autostart: bool | None = None,
        background_autostart: bool = True,
    ) -> None:
        self.controller = controller or ModelProxyController()
        self._autostart_started = False
        self.autostart = _truthy(os.getenv("MODEL_PROXY_AUTOSTART")) if autostart is None else autostart
        if self.autostart:
            self._start_autostart(background=background_autostart)

    def _start_autostart(self, *, background: bool) -> None:
        if self._autostart_started:
            return
        self._autostart_started = True
        if background:
            thread = threading.Thread(
                target=self._autostart_proxy,
                name="model-proxy-autostart",
                daemon=True,
            )
            thread.start()
            return
        self._autostart_proxy()

    def _autostart_proxy(self) -> None:
        status = self.controller.safe_status()
        if not status.get("proxy_running"):
            self.controller.start_proxy()

    def run(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            response = self.handle_line(line)
            if response is not None:
                stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
                stdout.flush()

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return self._error(None, -32700, "Parse error")
        return self.handle_message(message)

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        message_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if method == "initialize":
            protocol = params.get("protocolVersion") or "2024-11-05"
            return self._result(
                message_id,
                {
                    "protocolVersion": protocol,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._result(message_id, {})
        if method == "tools/list":
            return self._result(message_id, {"tools": tool_definitions()})
        if method == "resources/list":
            return self._result(message_id, {"resources": []})
        if method == "resources/templates/list":
            return self._result(message_id, {"resourceTemplates": []})
        if method == "tools/call":
            try:
                result = self._call_tool(str(params.get("name") or ""), params.get("arguments") or {})
            except ModelProxyError as exc:
                return self._result(message_id, tool_error(str(exc)))
            except Exception as exc:
                return self._result(message_id, tool_error(f"Unexpected MCP tool error: {exc}"))
            return self._result(message_id, tool_success(result))

        if message_id is None:
            return None
        return self._error(message_id, -32601, f"Method not found: {method}")

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "model_proxy_status":
            start_if_down = bool(arguments.get("start_if_down", False))
            if start_if_down:
                status = self.controller.safe_status()
                return self.controller.start_proxy() if not status.get("proxy_running") else status
            return self.controller.safe_status()

        if name == "list_models":
            return self.controller.list_models()

        if name == "switch_model":
            model = arguments.get("model")
            if not isinstance(model, str):
                raise ModelProxyError("switch_model requires a string `model` argument")
            return self.controller.switch_model(model)

        if name == "switch_provider":
            provider = arguments.get("provider")
            if not isinstance(provider, str):
                raise ModelProxyError("switch_provider requires a string `provider` argument")
            return self.controller.switch_provider(provider)

        if name == "start_model_proxy":
            return self.controller.start_proxy()

        raise ModelProxyError(f"Unknown tool: {name}")

    @staticmethod
    def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    @staticmethod
    def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def tool_success(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, indent=2, sort_keys=True),
            }
        ],
        "isError": False,
    }


def tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "model_proxy_status",
            "description": "Show whether the local model proxy is running, which backend model is active, and which stable model Codex should use.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_if_down": {
                        "type": "boolean",
                        "description": "If true, attempt to start the proxy when it is not responding.",
                        "default": False,
                    }
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "list_models",
            "description": "List switchable backend models for the configured local model proxy and show the active model.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "switch_model",
            "description": "Switch the backend model route used by the local model proxy for future requests.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Backend model route or alias to use next, such as opus, sonnet, openai:gpt-5.5, gpt, gemini, antigravity, grok, or cursor.",
                    }
                },
                "required": ["model"],
                "additionalProperties": False,
            },
        },
        {
            "name": "switch_provider",
            "description": "Switch to a provider's default backend model route for future requests.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Provider alias to use next, such as claude, openai, gpt, gemini, antigravity, grok, or cursor.",
                    }
                },
                "required": ["provider"],
                "additionalProperties": False,
            },
        },
        {
            "name": "start_model_proxy",
            "description": "Start the local model proxy process if it is not already running.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    ModelProxyMcpServer().run()


if __name__ == "__main__":
    main()
