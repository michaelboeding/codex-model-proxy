from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ModelProxyConfig:
    provider_id: str
    base_url: str
    api_key: str
    start_command: list[str]
    start_cwd: Path
    log_path: Path
    pid_path: Path
    start_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "ModelProxyConfig":
        base_url = os.getenv("MODEL_PROXY_BASE_URL") or os.getenv("PROXY_BASE_URL") or "http://127.0.0.1:8000"
        api_key = os.getenv("MODEL_PROXY_API_KEY") or os.getenv("PROXY_API_KEY") or "local-dev-key"
        start_cwd = Path(
            os.getenv("MODEL_PROXY_CWD") or os.getenv("PWD") or Path.cwd()
        ).expanduser()
        return cls(
            provider_id=os.getenv("MODEL_PROXY_PROVIDER_ID", "claude_code_cli_proxy"),
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            start_command=_start_command(base_url),
            start_cwd=start_cwd,
            log_path=Path(os.getenv("MODEL_PROXY_LOG_FILE", "~/.codex/model-proxy-control.log")).expanduser(),
            pid_path=Path(os.getenv("MODEL_PROXY_PID_FILE", "~/.codex/model-proxy.pid")).expanduser(),
            start_timeout_seconds=float(os.getenv("MODEL_PROXY_START_TIMEOUT_SECONDS", "10")),
        )


class ModelProxyController:
    def __init__(self, config: ModelProxyConfig | None = None) -> None:
        self.config = config or ModelProxyConfig.from_env()

    def status(self) -> dict[str, Any]:
        health = self._request_json("/health", authenticated=False)
        admin = self._request_json("/admin/model", authenticated=True)
        return {
            "provider_id": self.config.provider_id,
            "base_url": self.config.base_url,
            "proxy_running": True,
            "health": health,
            "active_model": admin.get("model"),
            "stable_model": admin.get("stable_model"),
            "default_model": admin.get("default_model"),
            "available_models": admin.get("available_models", []),
            "model_file": admin.get("model_file"),
        }

    def safe_status(self) -> dict[str, Any]:
        try:
            return self.status()
        except ModelProxyError as exc:
            return {
                "provider_id": self.config.provider_id,
                "base_url": self.config.base_url,
                "proxy_running": False,
                "error": str(exc),
            }

    def list_models(self) -> dict[str, Any]:
        return self.status()

    def switch_model(self, model: str) -> dict[str, Any]:
        if not model or not model.strip():
            raise ModelProxyError("model must be a non-empty string")
        result = self._request_json(
            "/admin/model",
            method="POST",
            body={"model": model.strip()},
            authenticated=True,
        )
        return {
            "provider_id": self.config.provider_id,
            "base_url": self.config.base_url,
            "proxy_running": True,
            "active_model": result.get("model"),
            "stable_model": result.get("stable_model"),
            "available_models": result.get("available_models", []),
            "model_file": result.get("model_file"),
        }

    def start_proxy(self) -> dict[str, Any]:
        status = self.safe_status()
        if status.get("proxy_running"):
            return {**status, "started": False, "message": "Proxy is already running."}

        self.config.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.pid_path.parent.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "PROXY_API_KEY": self.config.api_key,
        }
        log_file = self.config.log_path.open("ab")
        process = subprocess.Popen(
            self.config.start_command,
            cwd=self.config.start_cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        self.config.pid_path.write_text(str(process.pid) + "\n", encoding="utf-8")

        deadline = time.monotonic() + self.config.start_timeout_seconds
        last_error = status.get("error", "proxy was not running")
        while time.monotonic() < deadline:
            time.sleep(0.25)
            status = self.safe_status()
            if status.get("proxy_running"):
                return {
                    **status,
                    "started": True,
                    "pid": process.pid,
                    "log_file": str(self.config.log_path),
                }
            last_error = status.get("error", last_error)

        return {
            "provider_id": self.config.provider_id,
            "base_url": self.config.base_url,
            "proxy_running": False,
            "started": False,
            "pid": process.pid,
            "log_file": str(self.config.log_path),
            "error": f"Proxy did not become healthy within {self.config.start_timeout_seconds:g}s: {last_error}",
        }

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = Request(
            f"{self.config.base_url}{path}",
            data=payload,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ModelProxyError(f"Proxy returned HTTP {exc.code}: {details}") from exc
        except URLError as exc:
            raise ModelProxyError(f"Could not reach proxy at {self.config.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ModelProxyError(f"Proxy returned invalid JSON from {path}") from exc


class ModelProxyError(Exception):
    pass


def _start_command(base_url: str) -> list[str]:
    configured = os.getenv("MODEL_PROXY_START_COMMAND")
    if configured:
        import shlex

        return shlex.split(configured)

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 8000)
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "codex_model_proxy.server:app",
        "--host",
        host,
        "--port",
        port,
    ]

