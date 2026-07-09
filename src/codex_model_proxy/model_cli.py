from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description="Read or change the active backend model used by Codex Model Proxy.")
    parser.add_argument("model", nargs="?", help="Model to use next. Run with --list to see configured options.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("MODEL_PROXY_BASE_URL", os.getenv("PROXY_BASE_URL", "http://127.0.0.1:8000")),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MODEL_PROXY_API_KEY", os.getenv("PROXY_API_KEY", "local-dev-key")),
    )
    parser.add_argument("--list", action="store_true", help="Show available models.")
    args = parser.parse_args()

    try:
        if args.model:
            data = request_json(
                f"{args.base_url.rstrip('/')}/admin/model",
                api_key=args.api_key,
                method="POST",
                body={"model": args.model},
            )
        else:
            data = request_json(f"{args.base_url.rstrip('/')}/admin/model", api_key=args.api_key)
    except ProxyCliError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"active model: {data['model']}")
    print(f"Codex-facing model: {data['stable_model']}")
    if args.list or not args.model:
        print("available models:")
        for model in data["available_models"]:
            marker = "*" if model == data["model"] else "-"
            print(f"  {marker} {model}")
        routes = data.get("routes") or []
        if routes:
            print("routes:")
            for route in routes:
                if not isinstance(route, dict):
                    continue
                route_id = route.get("id")
                provider = route.get("provider")
                display_name = route.get("display_name")
                marker = "*" if route_id == data["model"] else "-"
                print(f"  {marker} {route_id} ({provider}) - {display_name}")


def request_json(
    url: str,
    *,
    api_key: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ProxyCliError(f"Proxy returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise ProxyCliError(f"Could not reach proxy at {url}: {exc.reason}") from exc


class ProxyCliError(Exception):
    pass


if __name__ == "__main__":
    main()
