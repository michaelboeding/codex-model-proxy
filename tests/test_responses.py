from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from codex_model_proxy import server
from codex_model_proxy.active_model import ActiveModelStore
from codex_model_proxy.claude_cli import ClaudeCliResult
from codex_model_proxy.providers import ProviderRegistry
from codex_model_proxy.responses import ModelResolver, ResponseStore, ResponsesService


class FakeClaudeClient:
    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.prompts: list[str] = []
        self.models: list[str] = []
        self.efforts: list[str | None] = []

    def complete(self, prompt: str, model: str, **kwargs: object) -> ClaudeCliResult:
        self.prompts.append(prompt)
        self.models.append(model)
        effort = kwargs.get("effort")
        self.efforts.append(effort if isinstance(effort, str) else None)
        text = self.replies.pop(0) if self.replies else "ok"
        return ClaudeCliResult(
            text=text,
            raw_events=[],
            usage={"input_tokens": 1, "output_tokens": 1},
            model=model,
        )


def install_fake_service(
    replies: list[str],
    active_model_store: ActiveModelStore | None = None,
) -> FakeClaudeClient:
    fake = FakeClaudeClient(replies)
    registry = ProviderRegistry()
    if active_model_store is None:
        test_path = Path("/tmp/codex-model-proxy-test-active-model")
        test_path.unlink(missing_ok=True)
        active_model_store = ActiveModelStore(path=test_path, registry=registry)
    server.active_model_store = active_model_store
    server.service = ResponsesService(
        fake,
        store=ResponseStore(),
        model_resolver=ModelResolver(registry=registry, active_model_store=active_model_store),
    )
    return fake


def client() -> TestClient:
    return TestClient(server.app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer local-dev-key"}


def test_health_does_not_require_auth() -> None:
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "codex-model-proxy"


def test_models_requires_auth() -> None:
    response = client().get("/v1/models")

    assert response.status_code == 401


def test_models_returns_openai_and_codex_shapes() -> None:
    response = client().get("/v1/models", headers=auth_headers())

    body = response.json()
    assert response.status_code == 200
    assert body["data"][0]["id"] == "claude"
    assert body["models"][0]["slug"] == "claude"
    assert body["models"][0]["display_name"] == "Model Proxy"
    assert body["models"][0]["supported_in_api"] is True
    assert body["models"][0]["service_tiers"][0]["id"] == "priority"
    assert "openai:gpt-5.5" in [item["id"] for item in body["data"]]
    assert "gemini:gemini-3-pro" in [item["id"] for item in body["data"]]
    assert "antigravity:gemini-3.5-flash-medium" in [item["id"] for item in body["data"]]
    assert "grok:grok-4.5" in [item["id"] for item in body["data"]]
    assert "cursor:auto" in [item["id"] for item in body["data"]]
    assert "cursor:gpt-5.3-codex" in [item["id"] for item in body["data"]]
    assert "cursor:claude-opus-4-8-thinking-high" in [item["id"] for item in body["data"]]
    assert "cursor:grok-4.5-xhigh" in [item["id"] for item in body["data"]]


def test_text_response() -> None:
    fake = install_fake_service(["Hello from Claude."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "claude-sonnet-5", "input": "Say hello."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "response"
    assert body["output_text"] == "Hello from Claude."
    assert body["output"][0]["type"] == "message"
    assert "Say hello." in fake.prompts[0]


def test_openai_mini_model_slug_routes_to_openai_backend() -> None:
    fake = install_fake_service(["OpenAI mini worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "gpt-5.4-mini", "input": "This was selected from the app picker."},
    )

    assert response.status_code == 200
    assert fake.models == ["openai:gpt-5.4-mini"]
    assert response.json()["model"] == "openai:gpt-5.4-mini"
    assert response.json()["output_text"] == "OpenAI mini worked."


def test_openai_model_slug_routes_to_openai_backend() -> None:
    fake = install_fake_service(["OpenAI route worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "gpt-5.5", "input": "This was selected from the app picker."},
    )

    assert response.status_code == 200
    assert fake.models == ["openai:gpt-5.5"]
    assert response.json()["model"] == "openai:gpt-5.5"
    assert response.json()["output_text"] == "OpenAI route worked."


def test_gemini_alias_routes_to_gemini_backend() -> None:
    fake = install_fake_service(["Gemini route worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "gemini", "input": "Use Gemini."},
    )

    assert response.status_code == 200
    assert fake.models == ["gemini:gemini-3-pro"]
    assert response.json()["model"] == "gemini:gemini-3-pro"


def test_antigravity_alias_routes_to_antigravity_backend() -> None:
    fake = install_fake_service(["Antigravity route worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "antigravity", "input": "Use Antigravity."},
    )

    assert response.status_code == 200
    assert fake.models == ["antigravity:gemini-3.5-flash-medium"]
    assert response.json()["model"] == "antigravity:gemini-3.5-flash-medium"


def test_grok_alias_routes_to_grok_backend() -> None:
    fake = install_fake_service(["Grok route worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "grok", "input": "Use Grok."},
    )

    assert response.status_code == 200
    assert fake.models == ["grok:grok-4.5"]
    assert response.json()["model"] == "grok:grok-4.5"


def test_cursor_alias_routes_to_cursor_backend() -> None:
    fake = install_fake_service(["Cursor route worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "cursor", "input": "Use Cursor."},
    )

    assert response.status_code == 200
    assert fake.models == ["cursor:auto"]
    assert response.json()["model"] == "cursor:auto"


def test_cursor_prefixed_aliases_route_to_current_cursor_catalog() -> None:
    fake = install_fake_service(
        [
            "Cursor Opus worked.",
            "Cursor GPT worked.",
            "Cursor Grok worked.",
            "Cursor Gemini worked.",
        ]
    )

    for selected_model in [
        "cursor:claude-opus-4-8",
        "cursor:gpt-5.5",
        "cursor:grok-4.5",
        "cursor:gemini-3-1-pro",
    ]:
        response = client().post(
            "/v1/responses",
            headers=auth_headers(),
            json={"model": selected_model, "input": "Use a Cursor model."},
        )
        assert response.status_code == 200

    assert fake.models == [
        "cursor:claude-opus-4-8-thinking-high",
        "cursor:gpt-5.5-high",
        "cursor:grok-4.5-xhigh",
        "cursor:gemini-3.1-pro",
    ]


def test_stable_claude_model_uses_active_model_store(tmp_path: Path) -> None:
    active_store = ActiveModelStore(path=tmp_path / "active-model")
    active_store.set("opus")
    fake = install_fake_service(["Active model worked."], active_store)

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "claude", "input": "Use the active model."},
    )

    assert response.status_code == 200
    assert fake.models == ["claude:opus"]
    assert response.json()["model"] == "claude:opus"
    assert response.json()["output_text"] == "Active model worked."


def test_admin_model_switch_changes_stable_model(tmp_path: Path) -> None:
    active_store = ActiveModelStore(path=tmp_path / "active-model")
    fake = install_fake_service(["Admin switch worked."], active_store)

    update = client().post(
        "/admin/model",
        headers=auth_headers(),
        json={"model": "claude-opus-4-8"},
    )
    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "claude", "input": "Use the active model."},
    )

    assert update.status_code == 200
    assert update.json()["model"] == "claude:claude-opus-4-8"
    assert response.status_code == 200
    assert fake.models == ["claude:claude-opus-4-8"]
    assert response.json()["output_text"] == "Admin switch worked."


def test_reasoning_effort_minimal_maps_to_claude_low() -> None:
    fake = install_fake_service(["Low effort worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "claude",
            "input": "Use low effort.",
            "reasoning": {"effort": "minimal"},
        },
    )

    assert response.status_code == 200
    assert fake.efforts == ["low"]


def test_reasoning_effort_extra_high_maps_to_claude_xhigh() -> None:
    fake = install_fake_service(["Xhigh effort worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "claude",
            "input": "Use extra high effort.",
            "model_reasoning_effort": "Extra High",
        },
    )

    assert response.status_code == 200
    assert fake.efforts == ["xhigh"]


def test_streaming_text_response_has_monotonic_sequence_numbers() -> None:
    install_fake_service(["Streaming answer."])

    with client().stream(
        "POST",
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "claude-sonnet-5", "input": "Stream please.", "stream": True},
    ) as response:
        text = response.read().decode()

    events = []
    for line in text.splitlines():
        if line.startswith("data: {"):
            events.append(json.loads(line.removeprefix("data: ")))

    assert response.status_code == 200
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    assert events[-1]["type"] == "response.completed"
    assert "data: [DONE]" in text


def test_tool_call_response() -> None:
    install_fake_service(
        ['<codex_function_call>{"name":"shell","arguments":{"cmd":"git status"}}</codex_function_call>']
    )

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "claude-sonnet-5",
            "input": "Check status.",
            "tools": [
                {
                    "type": "function",
                    "name": "shell",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                    },
                }
            ],
        },
    )

    body = response.json()
    item = body["output"][0]
    assert response.status_code == 200
    assert body["output_text"] == ""
    assert item["type"] == "function_call"
    assert item["name"] == "shell"
    assert json.loads(item["arguments"]) == {"cmd": "git status"}


def test_tool_result_follow_up_uses_previous_transcript() -> None:
    fake = install_fake_service(
        [
            '<codex_function_call>{"name":"shell","arguments":{"cmd":"git status"}}</codex_function_call>',
            "The worktree is clean.",
        ]
    )
    first = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "claude-sonnet-5",
            "input": "Check status.",
            "tools": [{"type": "function", "name": "shell", "parameters": {}}],
        },
    )
    call_id = first.json()["output"][0]["call_id"]

    second = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "claude-sonnet-5",
            "previous_response_id": first.json()["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": "On branch main\nnothing to commit",
                }
            ],
            "tools": [{"type": "function", "name": "shell", "parameters": {}}],
        },
    )

    assert second.status_code == 200
    assert second.json()["output_text"] == "The worktree is clean."
    assert "Requested Codex tool shell" in fake.prompts[1]
    assert "Codex tool result" in fake.prompts[1]
    assert "nothing to commit" in fake.prompts[1]


def test_bad_previous_response_id_returns_404() -> None:
    install_fake_service(["not used"])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "claude-sonnet-5",
            "previous_response_id": "resp_missing",
            "input": "Continue.",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "previous_response_not_found"
