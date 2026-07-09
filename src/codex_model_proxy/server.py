from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .active_model import ActiveModelStore
from .claude_cli import ClaudeCliClient, ClaudeCliError
from .providers import ProviderSpec, selected_provider
from .responses import ModelResolver, ResponseStore, ResponsesService


app = FastAPI(
    title="Codex Model Proxy",
    version=__version__,
    docs_url=None,
    redoc_url=None,
)


def configured_api_key() -> str | None:
    value = os.getenv("PROXY_API_KEY", "local-dev-key")
    return value or None


def require_auth(authorization: str | None = Header(default=None)) -> None:
    api_key = configured_api_key()
    if api_key is None:
        return
    expected = f"Bearer {api_key}"
    if authorization != expected:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing or invalid bearer token",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )


def make_provider() -> ProviderSpec:
    return selected_provider()


provider_spec = make_provider()


def make_active_model_store(provider: ProviderSpec | None = None) -> ActiveModelStore:
    return ActiveModelStore(provider=provider or provider_spec)


active_model_store = make_active_model_store()


def make_model_client(provider: ProviderSpec) -> ClaudeCliClient:
    if provider.backend_id == "claude_code":
        return ClaudeCliClient()
    raise RuntimeError(f"No model runner configured for backend provider '{provider.backend_id}'")


def make_service() -> ResponsesService:
    ttl = int(os.getenv("RESPONSE_TTL_SECONDS", "3600"))
    return ResponsesService(
        make_model_client(provider_spec),
        store=ResponseStore(ttl_seconds=ttl),
        model_resolver=ModelResolver(provider=provider_spec, active_model_store=active_model_store),
    )


service = make_service()


class ModelCatalog:
    def __init__(self, provider: ProviderSpec | None = None) -> None:
        self.provider = provider or provider_spec

    def names(self) -> list[str]:
        return self.provider.catalog_model_ids

    def openai_items(self) -> list[dict[str, Any]]:
        return [
            {
                "id": name,
                "object": "model",
                "created": 0,
                "owned_by": self.provider.owned_by,
            }
            for name in self.names()
        ]

    def codex_items(self) -> list[dict[str, Any]]:
        return [self._codex_model_info(name) for name in self.names()]

    def _codex_model_info(self, name: str) -> dict[str, Any]:
        return {
            "slug": name,
            "display_name": self.provider.display_name_for(name),
            "description": self.provider.catalog_description,
            "default_reasoning_level": "high",
            "supported_reasoning_levels": [
                {"effort": "minimal", "description": "Minimal reasoning, mapped to Claude low effort"},
                {"effort": "low", "description": "Fast responses with lighter reasoning"},
                {"effort": "medium", "description": "Balanced reasoning for everyday tasks"},
                {"effort": "high", "description": "Deeper reasoning for complex tasks"},
                {"effort": "xhigh", "description": "Extra high reasoning depth"},
                {"effort": "max", "description": "Maximum reasoning depth"},
            ],
            "shell_type": "shell_command",
            "visibility": "list",
            "supported_in_api": True,
            "priority": 1,
            "additional_speed_tiers": ["fast"],
            "service_tiers": [
                {
                    "id": "priority",
                    "name": "Fast",
                    "description": "Accepted for Codex compatibility; the local model runner chooses runtime behavior.",
                }
            ],
            "availability_nux": None,
            "upgrade": None,
            "base_instructions": (
                "You are Codex, a coding agent. Codex runs tools, file edits, approvals, "
                "and sandboxed commands. Use available Codex tools when needed; do not claim "
                "to have directly inspected or modified files unless Codex tool results show it."
            ),
            "model_messages": {
                "instructions_template": "{{ personality }}",
                "instructions_variables": {
                    "personality_default": "",
                    "personality_friendly": "",
                    "personality_pragmatic": "",
                },
            },
            "supports_reasoning_summaries": False,
            "default_reasoning_summary": "none",
            "support_verbosity": False,
            "default_verbosity": "medium",
            "apply_patch_tool_type": "freeform",
            "web_search_tool_type": "text_and_image",
            "truncation_policy": {"mode": "tokens", "limit": 10000},
            "supports_parallel_tool_calls": False,
            "supports_image_detail_original": False,
            "context_window": 200000,
            "max_context_window": 200000,
            "comp_hash": self.provider.comp_hash,
            "effective_context_window_percent": 90,
            "experimental_supported_tools": [],
            "input_modalities": ["text"],
            "supports_search_tool": False,
            "use_responses_lite": False,
        }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "codex-model-proxy",
        "version": __version__,
        "backend_provider": provider_spec.backend_id,
        "codex_provider_id": provider_spec.codex_provider_id,
        "backend_runner": provider_spec.runner_description,
        "backend_command": os.getenv("CLAUDE_COMMAND", "claude") if provider_spec.backend_id == "claude_code" else None,
        "stable_model": provider_spec.stable_model,
        "active_model": active_model_store.get(),
    }


@app.get("/admin/model", dependencies=[Depends(require_auth)])
def get_active_model() -> dict[str, Any]:
    return {
        "model": active_model_store.get(),
        "stable_model": provider_spec.stable_model,
        "default_model": active_model_store.default_model,
        "available_models": active_model_store.available_models,
        "model_file": str(active_model_store.path),
        "backend_provider": provider_spec.backend_id,
        "codex_provider_id": provider_spec.codex_provider_id,
    }


@app.post("/admin/model", dependencies=[Depends(require_auth)])
async def set_active_model(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid JSON request body", status_code=400, code="invalid_json")
    if not isinstance(body, dict):
        return error_response("Request body must be a JSON object", status_code=400)
    model = body.get("model")
    if not isinstance(model, str):
        return error_response("Request body must include a string model", status_code=400)
    try:
        active_model_store.set(model)
    except ValueError as exc:
        return error_response(str(exc), status_code=400, code="unknown_model")
    return JSONResponse(get_active_model())


@app.get("/v1/models", dependencies=[Depends(require_auth)])
def models() -> dict[str, Any]:
    catalog = ModelCatalog()
    return {
        "object": "list",
        "data": catalog.openai_items(),
        "models": catalog.codex_items(),
    }


@app.post("/v1/responses", dependencies=[Depends(require_auth)], response_model=None)
async def responses(request: Request):
    try:
        body = await request.json()
    except Exception as exc:
        return error_response("Invalid JSON request body", status_code=400, code="invalid_json")

    if not isinstance(body, dict):
        return error_response("Request body must be a JSON object", status_code=400)

    try:
        if body.get("stream"):
            return StreamingResponse(
                service.stream(body),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(service.create(body))
    except KeyError as exc:
        return error_response(
            f"Unknown previous_response_id: {exc.args[0]}",
            status_code=404,
            code="previous_response_not_found",
        )
    except ClaudeCliError as exc:
        return error_response(str(exc), status_code=502, code="model_backend_error")
    except Exception as exc:
        return error_response(str(exc), status_code=500, code="internal_error")


def error_response(message: str, *, status_code: int, code: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "code": code,
            }
        },
    )
