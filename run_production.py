"""Single-process threaded production entry point.

The application keeps crawler and scheduler state in memory, therefore it must run
as one process with multiple threads rather than several worker processes.
"""

from waitress import serve

from parser_app import app, ensure_storage
from parser_app.runtime import env_int, env_str


def validate_production_settings() -> None:
    secret = env_str("FLASK_SECRET_KEY", "change-this-secret-key")
    if secret == "change-this-secret-key" and env_str("ALLOW_INSECURE_DEFAULTS", "0") != "1":
        raise RuntimeError(
            "Set a strong FLASK_SECRET_KEY in .env before production start "
            "or explicitly set ALLOW_INSECURE_DEFAULTS=1 for a temporary test environment."
        )


def main() -> None:
    validate_production_settings()
    ensure_storage()
    host = env_str("HOST", "127.0.0.1")
    port = env_int("PORT", 5055, minimum=1, maximum=65535)
    threads = env_int("PRODUCTION_THREADS", 8, minimum=2, maximum=64)
    print(f"Serving parser on http://{host}:{port} with {threads} threads", flush=True)
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
