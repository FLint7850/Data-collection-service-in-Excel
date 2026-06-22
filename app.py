"""Compatibility entry point for local scripts."""

from parser_app import app
from parser_app.server import run

__all__ = ["app"]

if __name__ == "__main__":
    run()
