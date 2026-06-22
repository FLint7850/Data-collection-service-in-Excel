"""WSGI entry point for production servers (Waitress, Gunicorn, uWSGI)."""

from parser_app import app, ensure_storage

ensure_storage()

__all__ = ["app"]
