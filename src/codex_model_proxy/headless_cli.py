from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ModelBackendError


class HeadlessCliError(ModelBackendError):
    """Raised when a headless model CLI cannot produce a usable response."""


@dataclass(frozen=True)
class HeadlessCliResult:
    text: str
    raw_response: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    session_id: str | None = None


class HeadlessCliClient:
    """Configurable adapter for CLIs with a non-interactive prompt mode."""

    def __init__(
        self,
        *,
        label: str,
        command: str,
        args_template: str,
        cwd: str | Path | None = None,
        timeout_seconds: int = 300,
        error_type: type[ModelBackendError] = HeadlessCliError,
    ) -> None:
        self.label = label
        self.command = command
        self.args_template = args_template
        self.cwd = Path(cwd or os.getcwd())
        self.timeout_seconds = timeout_seconds
        self.error_type = error_type

    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> HeadlessCliResult:
        del max_output_tokens, temperature, top_p
        args = self._build_args(prompt, model, effort=effort)
        try:
            completed = subprocess.run(
                args,
                text=True,
                cwd=self.cwd,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise self.error_type(f"{self.label} command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise self.error_type(f"{self.label} timed out after {self.timeout_seconds}s") from exc

        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise self.error_type(f"{self.label} exited with {completed.returncode}: {details}")

        body = self._parse_response(completed.stdout)
        error = body.get("error")
        if error:
            raise self.error_type(self._error_text(error))
        if body.get("type") == "error":
            raise self.error_type(str(body.get("message") or f"{self.label} returned an error"))

        text = self._text_from_response(body)
        if not text:
            raise self.error_type(f"{self.label} completed without assistant text")

        return HeadlessCliResult(
            text=text,
            raw_response=body,
            usage=self._usage_from_response(body),
            model=model,
            session_id=self._session_id_from_response(body),
        )

    def _build_args(self, prompt: str, model: str, *, effort: str | None = None) -> list[str]:
        values = {
            "prompt": prompt,
            "model": model,
            "effort": effort or "",
        }
        args = shlex.split(self.command)
        for token in shlex.split(self.args_template):
            rendered = self._render_token(token, values)
            if rendered:
                args.append(rendered)
        return args

    @staticmethod
    def _render_token(token: str, values: dict[str, str]) -> str:
        rendered = token
        for key, value in values.items():
            rendered = rendered.replace(f"{{{key}}}", value)
        return rendered

    def _parse_response(self, stdout: str) -> dict[str, Any]:
        text = self._strip_ansi(stdout).strip()
        if not text:
            raise self.error_type(f"{self.label} returned empty output")
        parsed = self._json_from_text(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"response": self._text_from_json_value(parsed), "events": parsed}
        raise self.error_type(f"{self.label} returned unsupported JSON shape")

    def _json_from_text(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
            if not line.startswith(("{", "[")):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        return {"response": text}

    @staticmethod
    def _strip_ansi(value: str) -> str:
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)

    @classmethod
    def _text_from_response(cls, body: dict[str, Any]) -> str:
        for key in ("output_text", "response", "result", "text"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("message", "content", "output"):
            text = cls._text_from_json_value(body.get(key))
            if text:
                return text
        return ""

    @classmethod
    def _text_from_json_value(cls, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("text", "content", "message", "result", "response"):
                text = cls._text_from_json_value(value.get(key))
                if text:
                    return text
            return ""
        if isinstance(value, list):
            parts = [cls._text_from_json_value(item) for item in value]
            return "".join(part for part in parts if part)
        return ""

    @classmethod
    def _usage_from_response(cls, body: dict[str, Any]) -> dict[str, Any]:
        for key in ("usage", "stats", "token_usage"):
            usage = cls._usage_from_mapping(body.get(key))
            if usage:
                return usage
        return cls._usage_from_mapping(body)

    @staticmethod
    def _usage_from_mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        usage: dict[str, Any] = {}
        for source, target in {
            "input_tokens": "input_tokens",
            "prompt_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "completion_tokens": "output_tokens",
            "total_tokens": "total_tokens",
        }.items():
            token_count = value.get(source)
            if isinstance(token_count, int):
                usage[target] = token_count
        return usage

    @staticmethod
    def _session_id_from_response(body: dict[str, Any]) -> str | None:
        for key in ("session_id", "sessionId", "chat_id", "chatId"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _error_text(error: Any) -> str:
        if isinstance(error, str):
            return error
        if isinstance(error, dict):
            for key in ("message", "detail", "error"):
                value = error.get(key)
                if isinstance(value, str):
                    return value
        return str(error)
