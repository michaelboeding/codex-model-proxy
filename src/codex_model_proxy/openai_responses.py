from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import ModelBackendError


class OpenAIResponsesError(ModelBackendError):
    """Raised when the upstream OpenAI Responses API request fails."""


@dataclass(frozen=True)
class OpenAIResponsesResult:
    text: str
    raw_response: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


class OpenAIResponsesClient:
    """Small adapter around the upstream OpenAI Responses API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("MODEL_PROXY_OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout_seconds = timeout_seconds or int(os.getenv("OPENAI_TIMEOUT_SECONDS", "300"))

    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> OpenAIResponsesResult:
        if not self.api_key:
            raise OpenAIResponsesError("OPENAI_API_KEY is required to use OpenAI backend models")

        payload = self._build_payload(prompt, model, max_output_tokens, temperature, top_p, effort)
        request = Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise OpenAIResponsesError(f"OpenAI Responses API returned HTTP {exc.code}: {details}") from exc
        except URLError as exc:
            raise OpenAIResponsesError(f"Could not reach OpenAI Responses API at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise OpenAIResponsesError("OpenAI Responses API returned invalid JSON") from exc

        if not isinstance(body, dict):
            raise OpenAIResponsesError("OpenAI Responses API returned unsupported JSON shape")
        error = body.get("error")
        if error:
            raise OpenAIResponsesError(str(error))

        text = self._text_from_response(body)
        if not text:
            raise OpenAIResponsesError("OpenAI Responses API completed without assistant text")

        return OpenAIResponsesResult(
            text=text,
            raw_response=body,
            usage=dict(body.get("usage") or {}),
            model=str(body.get("model") or model),
        )

    @staticmethod
    def _build_payload(
        prompt: str,
        model: str,
        max_output_tokens: int | None,
        temperature: float | None,
        top_p: float | None,
        effort: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "input": prompt,
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        openai_effort = OpenAIResponsesClient._reasoning_effort(effort)
        if openai_effort:
            payload["reasoning"] = {"effort": openai_effort}
        return payload

    @staticmethod
    def _reasoning_effort(effort: str | None) -> str | None:
        if effort in {"low", "medium", "high"}:
            return effort
        if effort in {"xhigh", "max"}:
            return "high"
        return None

    @staticmethod
    def _text_from_response(body: dict[str, Any]) -> str:
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        chunks: list[str] = []
        for item in body.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    chunks.append(str(part.get("text") or ""))
        return "".join(chunks).strip()
