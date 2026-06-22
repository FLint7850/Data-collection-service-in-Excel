"""Parser application package."""

from parser_app.bootstrap import app
from parser_app import runtime

ensure_storage = runtime.ensure_storage

__all__ = ["app", "ensure_storage"]
