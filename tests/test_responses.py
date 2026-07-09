from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from codex_model_proxy import server
from codex_model_proxy.active_model import ActiveModelStore
from codex_model_proxy.claude_cli import ClaudeCliResult
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
    if active_model_store is None:
        test_path = Path("/tmp/codex-model-proxy-test-active-model")
        test_path.unlink(missing_ok=True)
        active_model_store = ActiveModelStore(path=test_path)
    server.active_model_store = active_model_store
    server.service = ResponsesService(
        fake,
        store=ResponseStore(),
        model_resolver=ModelResolver(active_model_store=active_model_store),
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
    assert body["models"][0]["display_name"] == "Claude"
    assert body["models"][0]["supported_in_api"] is True
    assert body["models"][0]["service_tiers"][0]["id"] == "priority"


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


def test_openai_model_slug_falls_back_to_latest_opus_alias() -> None:
    fake = install_fake_service(["Fallback worked."])

    response = client().post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "gpt-5.4-mini", "input": "This was selected from the app picker."},
    )

    assert response.status_code == 200
    assert fake.models == ["opus"]
    assert response.json()["model"] == "opus"
    assert response.json()["output_text"] == "Fallback worked."


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
    assert fake.models == ["opus"]
    assert response.json()["model"] == "opus"
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
    assert update.json()["model"] == "claude-opus-4-8"
    assert response.status_code == 200
    assert fake.models == ["claude-opus-4-8"]
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
