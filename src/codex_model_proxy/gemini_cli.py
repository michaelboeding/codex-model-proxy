from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ModelBackendError


class GeminiCliError(ModelBackendError):
    """Raised when the local gemini CLI cannot produce a usable response."""


@dataclass(frozen=True)
class GeminiCliResult:
    text: str
    raw_response: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    session_id: str | None = None


class GeminiCliClient:
    """Small adapter around the installed Gemini CLI command."""

    def __init__(
        self,
        command: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        approval_mode: str = "default",
        extensions: str | None = None,
    ) -> None:
        self.command = command or os.getenv("GEMINI_COMMAND", "gemini")
        self.cwd = Path(cwd or os.getenv("GEMINI_CWD", os.getcwd()))
        self.timeout_seconds = timeout_seconds or int(os.getenv("GEMINI_TIMEOUT_SECONDS", "300"))
        self.approval_mode = os.getenv("GEMINI_APPROVAL_MODE", approval_mode)
        self.extensions = os.getenv("GEMINI_EXTENSIONS", extensions or "none")

    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> GeminiCliResult:
        del max_output_tokens, temperature, top_p, effort
        args = self._build_args(prompt, model)
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
            raise GeminiCliError(f"Gemini CLI command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GeminiCliError(f"Gemini CLI timed out after {self.timeout_seconds}s") from exc

        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise GeminiCliError(f"Gemini CLI exited with {completed.returncode}: {details}")

        body = self._parse_response(completed.stdout)
        error = body.get("error")
        if error:
            raise GeminiCliError(str(error))

        text = str(body.get("response") or "").strip()
        if not text:
            raise GeminiCliError("Gemini CLI completed without assistant text")

        return GeminiCliResult(
            text=text,
            raw_response=body,
            usage=self._usage_from_stats(body.get("stats")),
            model=model,
            session_id=str(body.get("session_id") or "") or None,
        )

    def _build_args(self, prompt: str, model: str) -> list[str]:
        args = [
            self.command,
            "--model",
            model,
            "--approval-mode",
            self.approval_mode,
            "--output-format",
            "json",
        ]
        if self.extensions:
            args.extend(["--extensions", self.extensions])
        args.extend(["--prompt", prompt])
        return args

    @staticmethod
    def _parse_response(stdout: str) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            raise GeminiCliError("Gemini CLI returned empty output")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiCliError("Gemini CLI returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise GeminiCliError("Gemini CLI returned unsupported JSON shape")
        return parsed

    @staticmethod
    def _usage_from_stats(stats: Any) -> dict[str, Any]:
        if not isinstance(stats, dict):
            return {}
        usage: dict[str, Any] = {}
        for source, target in {
            "input_tokens": "input_tokens",
            "prompt_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "completion_tokens": "output_tokens",
        }.items():
            value = stats.get(source)
            if isinstance(value, int):
                usage[target] = value
        return usage
