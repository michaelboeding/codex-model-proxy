from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "codex_model_proxy.server:app",
        host=host,
        port=port,
        reload=os.getenv("RELOAD", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    main()

