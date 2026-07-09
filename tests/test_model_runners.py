from __future__ import annotations

from codex_model_proxy.antigravity_cli import AntigravityCliClient
from codex_model_proxy.cursor_agent import CursorAgentClient
from codex_model_proxy.gemini_cli import GeminiCliClient
from codex_model_proxy.grok_cli import GrokCliClient
from codex_model_proxy.headless_cli import HeadlessCliClient
from codex_model_proxy.openai_responses import OpenAIResponsesClient


def test_openai_payload_maps_extra_high_effort_to_high() -> None:
    payload = OpenAIResponsesClient._build_payload(
        "hello",
        "gpt-5.5",
        max_output_tokens=100,
        temperature=0.2,
        top_p=0.9,
        effort="xhigh",
    )

    assert payload == {
        "model": "gpt-5.5",
        "input": "hello",
        "max_output_tokens": 100,
        "temperature": 0.2,
        "top_p": 0.9,
        "reasoning": {"effort": "high"},
    }


def test_openai_text_from_response_uses_output_text_first() -> None:
    text = OpenAIResponsesClient._text_from_response(
        {
            "output_text": "hi",
            "output": [],
        }
    )

    assert text == "hi"


def test_openai_text_from_response_falls_back_to_message_parts() -> None:
    text = OpenAIResponsesClient._text_from_response(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello "},
                        {"type": "output_text", "text": "there"},
                    ],
                }
            ]
        }
    )

    assert text == "hello there"


def test_gemini_build_args_uses_noninteractive_json_with_default_approval() -> None:
    client = GeminiCliClient(command="gemini", cwd=".", timeout_seconds=1)

    args = client._build_args("hello", "gemini-3-pro")

    assert args == [
        "gemini",
        "--model",
        "gemini-3-pro",
        "--approval-mode",
        "default",
        "--output-format",
        "json",
        "--extensions",
        "none",
        "--prompt",
        "hello",
    ]


def test_gemini_parse_response_and_usage() -> None:
    body = GeminiCliClient._parse_response(
        '{"session_id":"abc","response":"hello","stats":{"input_tokens":2,"output_tokens":3}}'
    )
    usage = GeminiCliClient._usage_from_stats(body["stats"])

    assert body["response"] == "hello"
    assert usage == {"input_tokens": 2, "output_tokens": 3}


def test_grok_build_args_uses_single_turn_json_without_auto_approve() -> None:
    client = GrokCliClient(command="grok", cwd=".", timeout_seconds=1)

    args = client._build_args("hello", "grok-4.5")

    assert args == [
        "grok",
        "--single",
        "hello",
        "--model",
        "grok-4.5",
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--disable-web-search",
        "--no-subagents",
        "--permission-mode",
        "default",
        "--no-memory",
        "--verbatim",
    ]


def test_cursor_build_args_uses_print_json_model() -> None:
    client = CursorAgentClient(command="cursor-agent", cwd=".", timeout_seconds=1)

    args = client._build_args("hello", "auto")

    assert args == [
        "cursor-agent",
        "--print",
        "--output-format",
        "json",
        "--trust",
        "--model",
        "auto",
        "hello",
    ]


def test_antigravity_build_args_uses_agy_print_mode() -> None:
    client = AntigravityCliClient(command="agy", cwd=".", timeout_seconds=1)

    args = client._build_args("hello", "gemini-3.5-flash-medium")

    assert args == [
        "agy",
        "--print",
        "hello",
        "--model",
        "gemini-3.5-flash-medium",
        "--print-timeout",
        "5m",
    ]


def test_headless_cli_extracts_text_and_usage_from_result_shape() -> None:
    client = HeadlessCliClient(label="Test CLI", command="test", args_template="{prompt}", cwd=".")
    body = client._parse_response('{"result":"hello","usage":{"prompt_tokens":2,"completion_tokens":3}}')

    assert client._text_from_response(body) == "hello"
    assert client._usage_from_response(body) == {"input_tokens": 2, "output_tokens": 3}
