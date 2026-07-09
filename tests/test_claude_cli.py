from __future__ import annotations

import json

from codex_model_proxy.claude_cli import ClaudeCliClient


def test_parse_cli_events_ignores_unknown_rate_limit_event() -> None:
    stdout = json.dumps(
        [
            {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "private"},
                        {"type": "text", "text": "hello"},
                    ]
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "hello",
                "session_id": "session_123",
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        ]
    )

    events = ClaudeCliClient._parse_events(stdout)
    result = ClaudeCliClient._result_from_events(events)

    assert result.text == "hello"
    assert result.session_id == "session_123"
    assert result.usage["input_tokens"] == 2


def test_build_args_keeps_to_supported_cli_flags() -> None:
    client = ClaudeCliClient(command="claude", cwd=".", safe_mode=True)

    args = client._build_args(
        "claude-sonnet-5",
        max_output_tokens=100,
        temperature=0.1,
        top_p=0.5,
    )

    assert args == [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--model",
        "claude-sonnet-5",
        "--safe-mode",
        "--tools",
        "",
    ]


def test_build_args_includes_effort_when_requested() -> None:
    client = ClaudeCliClient(command="claude", cwd=".", safe_mode=False)

    args = client._build_args(
        "opus",
        max_output_tokens=None,
        temperature=None,
        top_p=None,
        effort="xhigh",
    )

    assert args == [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--model",
        "opus",
        "--effort",
        "xhigh",
        "--tools",
        "",
    ]
