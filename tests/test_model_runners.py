from __future__ import annotations

from codex_model_proxy.gemini_cli import GeminiCliClient
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
