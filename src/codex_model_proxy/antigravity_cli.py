from __future__ import annotations

import os
from pathlib import Path

from .errors import ModelBackendError
from .headless_cli import HeadlessCliClient, HeadlessCliResult


class AntigravityCliError(ModelBackendError):
    """Raised when the local Antigravity CLI cannot produce a usable response."""


class AntigravityCliClient(HeadlessCliClient):
    """Adapter around the installed Antigravity CLI command."""

    def __init__(
        self,
        command: str | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
        args_template: str | None = None,
    ) -> None:
        super().__init__(
            label="Antigravity CLI",
            command=command or os.getenv("ANTIGRAVITY_COMMAND", "antigravity"),
            args_template=args_template
            or os.getenv(
                "ANTIGRAVITY_ARGS_TEMPLATE",
                "--model {model} --output-format json --prompt {prompt}",
            ),
            cwd=cwd or os.getenv("ANTIGRAVITY_CWD", os.getcwd()),
            timeout_seconds=timeout_seconds or int(os.getenv("ANTIGRAVITY_TIMEOUT_SECONDS", "300")),
            error_type=AntigravityCliError,
        )


AntigravityCliResult = HeadlessCliResult
