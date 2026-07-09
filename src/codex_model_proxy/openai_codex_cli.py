from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ModelBackendError


class OpenAICodexCliError(ModelBackendError):
    """Raised when the local Codex CLI cannot produce a usable response."""


@dataclass(frozen=True)
class OpenAICodexCliResult:
    text: str
    raw_response: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    session_id: str | None = None


class OpenAICodexCliClient:
    """Adapter around `codex exec` using the user's local Codex subscription auth."""

    def __init__(
        self,
        command: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        sandbox: str | None = None,
    ) -> None:
        self.command = command or os.getenv("OPENAI_CODEX_COMMAND", os.getenv("CODEX_COMMAND", "codex"))
        self.cwd = Path(cwd or os.getenv("OPENAI_CODEX_CWD", tempfile.gettempdir()))
        self.timeout_seconds = timeout_seconds or int(os.getenv("OPENAI_CODEX_TIMEOUT_SECONDS", "300"))
        self.sandbox = os.getenv("OPENAI_CODEX_SANDBOX", sandbox or "read-only")
        self.ignore_user_config = self._env_bool("OPENAI_CODEX_IGNORE_USER_CONFIG", default=True)
        self.ephemeral = self._env_bool("OPENAI_CODEX_EPHEMERAL", default=True)
        self.skip_git_repo_check = self._env_bool("OPENAI_CODEX_SKIP_GIT_REPO_CHECK", default=True)
        self.pass_reasoning_effort = self._env_bool("OPENAI_CODEX_PASS_REASONING_EFFORT", default=True)
        self.extra_args = shlex.split(os.getenv("OPENAI_CODEX_EXTRA_ARGS", ""))

    def complete(
        self,
        prompt: str,
        model: str,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        effort: str | None = None,
    ) -> OpenAICodexCliResult:
        del max_output_tokens, temperature, top_p
        output_fd, output_name = tempfile.mkstemp(prefix="codex-model-proxy-", suffix=".txt")
        os.close(output_fd)
        output_path = Path(output_name)
        args = self._build_args(prompt, model, effort=effort, output_file=output_path)
        try:
            completed = subprocess.run(
                args,
                text=True,
                cwd=self.cwd,
                input="",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise OpenAICodexCliError(f"Codex CLI command not found: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise OpenAICodexCliError(f"Codex CLI timed out after {self.timeout_seconds}s") from exc
        try:
            if completed.returncode != 0:
                details = completed.stderr.strip() or completed.stdout.strip()
                raise OpenAICodexCliError(f"Codex CLI exited with {completed.returncode}: {details}")

            text = self._read_output_text(output_path, completed.stdout)
            if not text:
                raise OpenAICodexCliError("Codex CLI completed without assistant text")

            return OpenAICodexCliResult(
                text=text,
                raw_response={
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "output_file": str(output_path),
                },
                model=model,
            )
        finally:
            output_path.unlink(missing_ok=True)

    def _build_args(self, prompt: str, model: str, *, effort: str | None = None, output_file: Path) -> list[str]:
        args = shlex.split(self.command)
        args.append("exec")
        if self.ignore_user_config:
            args.append("--ignore-user-config")
        if self.ephemeral:
            args.append("--ephemeral")
        if self.skip_git_repo_check:
            args.append("--skip-git-repo-check")
        if self.sandbox:
            args.extend(["--sandbox", self.sandbox])
        if self.pass_reasoning_effort:
            effort_config = self._reasoning_effort_config(effort)
            if effort_config:
                args.extend(["-c", f"model_reasoning_effort={json.dumps(effort_config)}"])
        args.extend(self.extra_args)
        args.extend(["--model", model, "--output-last-message", str(output_file), prompt])
        return args

    @staticmethod
    def _read_output_text(output_path: Path, stdout: str) -> str:
        if output_path.exists():
            text = output_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        return stdout.strip()

    @staticmethod
    def _reasoning_effort_config(effort: str | None) -> str | None:
        if effort in {"low", "medium", "high", "xhigh", "max"}:
            return effort
        return None

    @staticmethod
    def _env_bool(name: str, *, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
