from __future__ import annotations

import os
from pathlib import Path

from .errors import ModelBackendError
from .headless_cli import HeadlessCliClient, HeadlessCliResult


class GrokCliError(ModelBackendError):
    """Raised when the local Grok CLI cannot produce a usable response."""


class GrokCliClient(HeadlessCliClient):
    """Adapter around the installed Grok CLI command."""

    def __init__(
        self,
        command: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        args_template: str | None = None,
    ) -> None:
        super().__init__(
            label="Grok CLI",
            command=command or os.getenv("GROK_COMMAND", "grok"),
            args_template=args_template
            or os.getenv(
                "GROK_ARGS_TEMPLATE",
                "--single {prompt} --model {model} --output-format json --max-turns 1 "
                "--disable-web-search --no-subagents --permission-mode default --no-memory --verbatim",
            ),
            cwd=cwd or os.getenv("GROK_CWD", os.getcwd()),
            timeout_seconds=timeout_seconds or int(os.getenv("GROK_TIMEOUT_SECONDS", "300")),
            error_type=GrokCliError,
        )


GrokCliResult = HeadlessCliResult
