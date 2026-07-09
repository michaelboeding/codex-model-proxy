from __future__ import annotations


class ModelBackendError(RuntimeError):
    """Raised when a configured model backend cannot produce a usable response."""
