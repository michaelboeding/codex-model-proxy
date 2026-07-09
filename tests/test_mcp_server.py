from __future__ import annotations

import json

from codex_model_proxy.mcp_server import ModelProxyMcpServer


class FakeController:
    def __init__(self) -> None:
        self.active_model = "sonnet"
        self.started = False

    def safe_status(self):
        return {
            "provider_id": "test_provider",
            "base_url": "http://127.0.0.1:8000",
            "proxy_running": True,
            "active_model": self.active_model,
            "stable_model": "claude",
            "available_models": ["sonnet", "opus"],
        }

    def list_models(self):
        return self.safe_status()

    def switch_model(self, model: str):
        self.active_model = model
        return self.safe_status()

    def switch_provider(self, provider: str):
        self.active_model = provider
        return self.safe_status()

    def start_proxy(self):
        self.started = True
        return {**self.safe_status(), "started": True}


class DownThenStartController(FakeController):
    def safe_status(self):
        status = super().safe_status()
        return {**status, "proxy_running": self.started}


def test_initialize_returns_tools_capability() -> None:
    server = ModelProxyMcpServer(FakeController())

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )

    assert response["result"]["capabilities"] == {"tools": {}, "resources": {}}
    assert response["result"]["serverInfo"]["name"] == "model-proxy-control"
    assert "local model proxy" in response["result"]["instructions"]


def test_tools_list_is_generic() -> None:
    server = ModelProxyMcpServer(FakeController())

    response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [tool["name"] for tool in response["result"]["tools"]]

    assert names == [
        "model_proxy_status",
        "list_models",
        "switch_model",
        "switch_provider",
        "start_model_proxy",
    ]


def test_resources_lists_are_empty() -> None:
    server = ModelProxyMcpServer(FakeController())

    resources = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    templates = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"})

    assert resources["result"] == {"resources": []}
    assert templates["result"] == {"resourceTemplates": []}


def test_switch_model_tool_returns_json_content() -> None:
    controller = FakeController()
    server = ModelProxyMcpServer(controller)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "switch_model", "arguments": {"model": "opus"}},
        }
    )

    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload["active_model"] == "opus"
    assert payload["stable_model"] == "claude"


def test_switch_provider_tool_returns_json_content() -> None:
    controller = FakeController()
    server = ModelProxyMcpServer(controller)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "switch_provider", "arguments": {"provider": "gemini"}},
        }
    )

    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload["active_model"] == "gemini"


def test_status_can_start_if_down() -> None:
    controller = FakeController()
    server = ModelProxyMcpServer(controller)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "start_model_proxy", "arguments": {}},
        }
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert controller.started is True
    assert payload["started"] is True


def test_autostart_starts_proxy_when_enabled() -> None:
    controller = DownThenStartController()

    ModelProxyMcpServer(controller, autostart=True, background_autostart=False)

    assert controller.started is True
