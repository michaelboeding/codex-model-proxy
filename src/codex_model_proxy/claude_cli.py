from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ModelBackendError


class ClaudeCliError(ModelBackendError):
    """Raised when the local claude CLI cannot produce a usable response."""


@dataclass(frozen=True)
class ClaudeCliResult:
    text: str
    raw_events: list[dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    session_id: str | None = None
    total_cost_usd: float | None = None


class ClaudeCliClient:
    """Small adapter around the installed Claude Code terminal command."""

    def __init__(
        self,
        command: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        safe_mode: bool | None = None,
        disable_tools: bool = True,
        permission_mode: str = "dontAsk",
    ) -> None:
        self.command = command or os.getenv("CLAUDE_COMMAND", "claude")
        self.cwd = Path(cwd or os.getenv("CLAUDE_CWD", os.getcwd()))
        self.timeout_seconds = timeout_seconds or int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "300"))
        self.safe_mode = (
            safe_mode
            if safe_mode is not None
            else os.getenv("CLAUDE_SAFE_MODE", "1").lower() not in {"0", "false", "no"}
        )
        self.disable_tools = disable_tools
        self.permission_mode = os.getenv("CLAUDE_PERMISSION_MODE", permission_mode)

    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> ClaudeCliResult:
        args = self._build_args(model, max_output_tokens, temperature, top_p, effort)
        try:
            completed = subprocess.run(
                args,
                input=prompt,
                text=True,
                cwd=self.cwd,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ClaudeCliError(f"Claude CLI command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCliError(f"Claude CLI timed out after {self.timeout_seconds}s") from exc

        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise ClaudeCliError(f"Claude CLI exited with {completed.returncode}: {details}")

        events = self._parse_events(completed.stdout)
        return self._result_from_events(events)

    def _build_args(
        self,
        model: str,
        max_output_tokens: int | None,
        temperature: float | None,
        top_p: float | None,
        effort: str | None = None,
    ) -> list[str]:
        del max_output_tokens, temperature, top_p
        args = [
            self.command,
            "--print",
            "--output-format",
            "json",
            "--permission-mode",
            self.permission_mode,
            "--model",
            model,
        ]

        if effort:
            args.extend(["--effort", effort])

        if self.safe_mode:
            args.append("--safe-mode")

        if self.disable_tools:
            args.extend(["--tools", ""])

        return args

    @classmethod
    def _parse_events(cls, stdout: str) -> list[dict[str, Any]]:
        text = stdout.strip()
        if not text:
            raise ClaudeCliError("Claude CLI returned empty output")

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = cls._parse_json_lines(text)

        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [event for event in parsed if isinstance(event, dict)]
        raise ClaudeCliError("Claude CLI returned unsupported JSON shape")

    @staticmethod
    def _parse_json_lines(text: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ClaudeCliError("Claude CLI returned invalid JSON") from exc
            if isinstance(parsed, dict):
                events.append(parsed)
        if not events:
            raise ClaudeCliError("Claude CLI returned no JSON events")
        return events

    @staticmethod
    def _result_from_events(events: list[dict[str, Any]]) -> ClaudeCliResult:
        result_event = next(
            (event for event in reversed(events) if event.get("type") == "result"),
            None,
        )
        if result_event and result_event.get("is_error"):
            message = result_event.get("result") or result_event.get("subtype") or "Claude CLI error"
            raise ClaudeCliError(str(message))

        text = str(result_event.get("result") or "") if result_event else ""
        if not text:
            text = ClaudeCliClient._assistant_text_from_events(events)

        if not text:
            raise ClaudeCliError("Claude CLI completed without assistant text")

        system_event = next((event for event in events if event.get("type") == "system"), {})
        return ClaudeCliResult(
            text=text,
            raw_events=events,
            usage=dict(result_event.get("usage") or {}) if result_event else {},
            model=result_event.get("model") or system_event.get("model"),
            session_id=result_event.get("session_id") or system_event.get("session_id"),
            total_cost_usd=result_event.get("total_cost_usd") if result_event else None,
        )

    @staticmethod
    def _assistant_text_from_events(events: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        for event in events:
            if event.get("type") != "assistant":
                continue
            message = event.get("message") or {}
            for part in message.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "text":
                    chunks.append(str(part.get("text") or ""))
        return "".join(chunks).strip()
