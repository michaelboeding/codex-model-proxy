from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from .active_model import ActiveModelStore
from .providers import ProviderRegistry


TOOL_CALL_RE = re.compile(
    r"<codex_function_call>\s*(\{.*?\})\s*</codex_function_call>",
    re.DOTALL,
)


@dataclass(frozen=True)
class TranscriptMessage:
    role: str
    content: str


@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:24]}")

    @property
    def arguments_json(self) -> str:
        return json.dumps(self.arguments, separators=(",", ":"), ensure_ascii=False)


@dataclass
class StoredResponse:
    response_id: str
    transcript: list[TranscriptMessage]
    created_at: float
    output: list[dict[str, Any]]


class ResponseStore:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self.ttl_seconds = ttl_seconds
        self._responses: dict[str, StoredResponse] = {}

    def get_transcript(self, response_id: str) -> list[TranscriptMessage]:
        self.cleanup()
        stored = self._responses.get(response_id)
        if stored is None:
            raise KeyError(response_id)
        return list(stored.transcript)

    def put(self, response_id: str, transcript: list[TranscriptMessage], output: list[dict[str, Any]]) -> None:
        self.cleanup()
        self._responses[response_id] = StoredResponse(
            response_id=response_id,
            transcript=list(transcript),
            created_at=time.time(),
            output=output,
        )

    def cleanup(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        expired = [
            response_id
            for response_id, stored in self._responses.items()
            if stored.created_at < cutoff
        ]
        for response_id in expired:
            del self._responses[response_id]


class InputNormalizer:
    def normalize(self, body: dict[str, Any]) -> list[TranscriptMessage]:
        messages: list[TranscriptMessage] = []
        instructions = body.get("instructions")
        if instructions:
            messages.append(TranscriptMessage("system", str(instructions)))

        input_value = body.get("input")
        if input_value is None:
            return messages
        if isinstance(input_value, str):
            messages.append(TranscriptMessage("user", input_value))
            return messages
        if isinstance(input_value, list):
            for item in input_value:
                messages.extend(self._normalize_item(item))
            return messages

        messages.append(TranscriptMessage("user", self._jsonish(input_value)))
        return messages

    def _normalize_item(self, item: Any) -> list[TranscriptMessage]:
        if isinstance(item, str):
            return [TranscriptMessage("user", item)]
        if not isinstance(item, dict):
            return [TranscriptMessage("user", self._jsonish(item))]

        item_type = item.get("type")
        if item_type == "function_call_output":
            call_id = item.get("call_id", "unknown_call")
            output = self._content_to_text(item.get("output", ""))
            content = f"Codex tool result for {call_id}:\n{output}"
            return [TranscriptMessage("tool", content)]

        if item_type == "function_call":
            name = item.get("name", "unknown_tool")
            call_id = item.get("call_id", "unknown_call")
            args = item.get("arguments", {})
            content = f"Assistant requested Codex tool {name} with call_id {call_id} and arguments {args}."
            return [TranscriptMessage("assistant", content)]

        if item_type == "message" or "role" in item:
            role = self._map_role(str(item.get("role", "user")))
            content = self._content_to_text(item.get("content", ""))
            return [TranscriptMessage(role, content)]

        if item_type in {"input_text", "output_text", "text"}:
            return [TranscriptMessage("user", str(item.get("text", "")))]

        return [TranscriptMessage("user", self._jsonish(item))]

    def _content_to_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    if "text" in part:
                        parts.append(str(part.get("text") or ""))
                    elif part.get("type") == "function_call_output":
                        parts.append(str(part.get("output") or ""))
                    else:
                        parts.append(self._jsonish(part))
                else:
                    parts.append(self._jsonish(part))
            return "\n".join(part for part in parts if part)
        if isinstance(content, dict):
            if "text" in content:
                return str(content.get("text") or "")
            return self._jsonish(content)
        return str(content)

    @staticmethod
    def _map_role(role: str) -> str:
        if role in {"system", "developer"}:
            return "system"
        if role in {"assistant", "tool"}:
            return role
        return "user"

    @staticmethod
    def _jsonish(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)


class ToolAdapter:
    def build_tool_instructions(self, tools: list[dict[str, Any]], tool_choice: Any = None) -> str:
        functions = [tool for tool in (self._normalize_tool(tool) for tool in tools) if tool]
        if not functions:
            return ""

        rendered = "\n".join(json.dumps(tool, ensure_ascii=False, sort_keys=True) for tool in functions)
        choice = f"\nTool choice requested by Codex: {self._jsonish(tool_choice)}" if tool_choice else ""
        return (
            "Codex will run tools for you. Claude Code terminal tools are disabled, so do not claim "
            "to have read or edited local files yourself.\n"
            "When you need a tool, respond with exactly one XML block and no surrounding prose:\n"
            '<codex_function_call>{"name":"tool_name","arguments":{}}</codex_function_call>\n'
            "Use only one tool call at a time. After Codex returns the tool result in a later message, "
            "continue from that result.\n"
            f"Available Codex tools:\n{rendered}{choice}"
        )

    def parse_function_call(self, text: str) -> FunctionCall | None:
        match = TOOL_CALL_RE.search(text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or not payload.get("name"):
            return None
        arguments = payload.get("arguments", {})
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
                arguments = parsed if isinstance(parsed, dict) else {"value": arguments}
            except json.JSONDecodeError:
                arguments = {"value": arguments}
        if not isinstance(arguments, dict):
            arguments = {}
        return FunctionCall(name=str(payload["name"]), arguments=arguments)

    def _normalize_tool(self, tool: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(tool, dict):
            return None
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            function = tool["function"]
            return {
                "name": function.get("name"),
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {}),
            }
        if tool.get("type") == "function":
            return {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            }
        return None

    @staticmethod
    def _jsonish(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)


class PromptBuilder:
    def build(self, transcript: list[TranscriptMessage], tool_instructions: str = "") -> str:
        sections: list[str] = []
        if tool_instructions:
            sections.append(f"<codex_proxy_instructions>\n{tool_instructions}\n</codex_proxy_instructions>")
        sections.append("<conversation>")
        for message in transcript:
            role = message.role
            content = message.content.strip()
            sections.append(f"<{role}>\n{content}\n</{role}>")
        sections.append("</conversation>")
        sections.append("Respond to the latest user or tool result.")
        return "\n\n".join(sections)


class ResponseFormatter:
    def text_output_item(self, text: str) -> dict[str, Any]:
        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                    "annotations": [],
                }
            ],
        }

    def function_output_item(self, call: FunctionCall) -> dict[str, Any]:
        return {
            "id": f"fc_{uuid.uuid4().hex[:24]}",
            "type": "function_call",
            "status": "completed",
            "call_id": call.call_id,
            "name": call.name,
            "arguments": call.arguments_json,
        }

    def response_object(
        self,
        *,
        response_id: str,
        body: dict[str, Any],
        output: list[dict[str, Any]],
        output_text: str,
        usage: dict[str, Any],
        status: str = "completed",
    ) -> dict[str, Any]:
        created_at = int(time.time())
        return {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "status": status,
            "error": None,
            "incomplete_details": None,
            "instructions": body.get("instructions"),
            "max_output_tokens": body.get("max_output_tokens"),
            "model": body.get("model", "opus"),
            "output": output,
            "output_text": output_text,
            "parallel_tool_calls": False,
            "previous_response_id": body.get("previous_response_id"),
            "reasoning": body.get("reasoning"),
            "store": body.get("store", True),
            "temperature": body.get("temperature"),
            "text": body.get("text", {"format": {"type": "text"}}),
            "tool_choice": body.get("tool_choice", "auto"),
            "tools": body.get("tools", []),
            "top_p": body.get("top_p"),
            "truncation": body.get("truncation", "disabled"),
            "usage": self._openai_usage(usage),
            "user": body.get("user"),
            "metadata": body.get("metadata") or {},
        }

    @staticmethod
    def _openai_usage(usage: dict[str, Any]) -> dict[str, Any]:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        cache_created = int(usage.get("cache_creation_input_tokens") or 0)
        return {
            "input_tokens": input_tokens,
            "input_tokens_details": {
                "cached_tokens": cache_read,
                "cache_creation_tokens": cache_created,
            },
            "output_tokens": output_tokens,
            "output_tokens_details": {
                "reasoning_tokens": 0,
            },
            "total_tokens": input_tokens + output_tokens,
        }


class CompletionResult(Protocol):
    text: str
    usage: dict[str, Any]


class ModelClient(Protocol):
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


class SseEncoder:
    def __init__(self) -> None:
        self.sequence_number = 0

    def event(self, event_type: str, **payload: Any) -> str:
        data = {
            "type": event_type,
            "sequence_number": self.sequence_number,
            **payload,
        }
        self.sequence_number += 1
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def done() -> str:
        return "data: [DONE]\n\n"


class ModelResolver:
    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        active_model_store: ActiveModelStore | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.active_model_store = active_model_store or ActiveModelStore(registry=self.registry)

    def resolve(self, requested_model: Any) -> str:
        return self.registry.resolve_request_model(requested_model, self.active_model_store.get())


class ReasoningEffortResolver:
    aliases = {
        "minimal": "low",
        "min": "low",
        "light": "low",
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "extra_high": "xhigh",
        "extra-high": "xhigh",
        "extra high": "xhigh",
        "xhigh": "xhigh",
        "max": "max",
        "maximum": "max",
    }

    def resolve(self, body: dict[str, Any]) -> str | None:
        for value in self._candidate_values(body):
            normalized = self._normalize(value)
            if normalized:
                return normalized
        return None

    def _candidate_values(self, body: dict[str, Any]) -> Iterable[Any]:
        reasoning = body.get("reasoning")
        if isinstance(reasoning, dict):
            yield reasoning.get("effort")
            yield reasoning.get("level")
        yield body.get("reasoning_effort")
        yield body.get("model_reasoning_effort")

    def _normalize(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        key = value.strip().lower().replace(" ", "_")
        return self.aliases.get(key)


class ResponsesService:
    def __init__(
        self,
        model_client: ModelClient,
        store: ResponseStore | None = None,
        normalizer: InputNormalizer | None = None,
        tool_adapter: ToolAdapter | None = None,
        prompt_builder: PromptBuilder | None = None,
        formatter: ResponseFormatter | None = None,
        model_resolver: ModelResolver | None = None,
        effort_resolver: ReasoningEffortResolver | None = None,
    ) -> None:
        self.model_client = model_client
        self.store = store or ResponseStore()
        self.normalizer = normalizer or InputNormalizer()
        self.tool_adapter = tool_adapter or ToolAdapter()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.formatter = formatter or ResponseFormatter()
        self.model_resolver = model_resolver or ModelResolver()
        self.effort_resolver = effort_resolver or ReasoningEffortResolver()

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self._complete(body)
        return response

    def stream(self, body: dict[str, Any]) -> Iterable[str]:
        response = self._complete(body)
        encoder = SseEncoder()
        in_progress = {**response, "status": "in_progress", "output": [], "output_text": ""}
        yield encoder.event("response.created", response=in_progress)
        yield encoder.event("response.in_progress", response=in_progress)
        for index, item in enumerate(response["output"]):
            yield encoder.event("response.output_item.added", output_index=index, item=item)
            if item["type"] == "message":
                text_part = item["content"][0]
                yield encoder.event(
                    "response.content_part.added",
                    item_id=item["id"],
                    output_index=index,
                    content_index=0,
                    part={**text_part, "text": ""},
                )
                text = text_part.get("text", "")
                if text:
                    yield encoder.event(
                        "response.output_text.delta",
                        item_id=item["id"],
                        output_index=index,
                        content_index=0,
                        delta=text,
                    )
                yield encoder.event(
                    "response.output_text.done",
                    item_id=item["id"],
                    output_index=index,
                    content_index=0,
                    text=text,
                )
                yield encoder.event(
                    "response.content_part.done",
                    item_id=item["id"],
                    output_index=index,
                    content_index=0,
                    part=text_part,
                )
            elif item["type"] == "function_call":
                arguments = item.get("arguments", "")
                if arguments:
                    yield encoder.event(
                        "response.function_call_arguments.delta",
                        item_id=item["id"],
                        output_index=index,
                        delta=arguments,
                    )
                yield encoder.event(
                    "response.function_call_arguments.done",
                    item_id=item["id"],
                    output_index=index,
                    arguments=arguments,
                )
            yield encoder.event("response.output_item.done", output_index=index, item=item)
        yield encoder.event("response.completed", response=response)
        yield encoder.done()

    def _complete(self, body: dict[str, Any]) -> dict[str, Any]:
        model = self.model_resolver.resolve(body.get("model"))
        response_body = {**body, "model": model}
        previous_response_id = body.get("previous_response_id")
        transcript: list[TranscriptMessage] = []
        if previous_response_id:
            transcript.extend(self.store.get_transcript(str(previous_response_id)))
        transcript.extend(self.normalizer.normalize(body))

        tool_instructions = self.tool_adapter.build_tool_instructions(
            list(body.get("tools") or []),
            body.get("tool_choice"),
        )
        prompt = self.prompt_builder.build(transcript, tool_instructions)
        result = self.model_client.complete(
            prompt,
            model,
            max_output_tokens=body.get("max_output_tokens"),
            temperature=body.get("temperature"),
            top_p=body.get("top_p"),
            effort=self.effort_resolver.resolve(body),
        )

        function_call = self.tool_adapter.parse_function_call(result.text) if body.get("tools") else None
        response_id = f"resp_{uuid.uuid4().hex[:24]}"
        if function_call:
            output = [self.formatter.function_output_item(function_call)]
            output_text = ""
            transcript.append(
                TranscriptMessage(
                    "assistant",
                    f"Requested Codex tool {function_call.name} with call_id {function_call.call_id} "
                    f"and arguments {function_call.arguments_json}.",
                )
            )
        else:
            text = self._strip_protocol(result.text)
            output = [self.formatter.text_output_item(text)]
            output_text = text
            transcript.append(TranscriptMessage("assistant", text))

        response = self.formatter.response_object(
            response_id=response_id,
            body=response_body,
            output=output,
            output_text=output_text,
            usage=result.usage,
        )
        self.store.put(response_id, transcript, output)
        return response

    @staticmethod
    def _strip_protocol(text: str) -> str:
        return TOOL_CALL_RE.sub("", text).strip()
