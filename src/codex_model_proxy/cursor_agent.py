from __future__ import annotations

import os
from pathlib import Path

from .errors import ModelBackendError
from .headless_cli import HeadlessCliClient, HeadlessCliResult


class CursorAgentError(ModelBackendError):
    """Raised when the local Cursor Agent CLI cannot produce a usable response."""


class CursorAgentClient(HeadlessCliClient):
    """Adapter around the installed Cursor Agent CLI command."""

    def __init__(
        self,
        command: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        args_template: str | None = None,
    ) -> None:
        super().__init__(
            label="Cursor Agent CLI",
            command=command or os.getenv("CURSOR_COMMAND", "cursor-agent"),
            args_template=args_template
            or os.getenv(
                "CURSOR_ARGS_TEMPLATE",
                "--print --output-format json --model {model} {prompt}",
            ),
            cwd=cwd or os.getenv("CURSOR_CWD", os.getcwd()),
            timeout_seconds=timeout_seconds or int(os.getenv("CURSOR_TIMEOUT_SECONDS", "300")),
            error_type=CursorAgentError,
        )


CursorAgentResult = HeadlessCliResult
