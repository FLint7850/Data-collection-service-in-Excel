"""Flask application assembly and blueprint registration."""

import faulthandler

from flask import Flask

from config import env_int, env_str
from routes import BLUEPRINTS
from services import application as application_service


def create_app() -> Flask:
    application = Flask(__name__, static_folder=None)
    application.secret_key = env_str("FLASK_SECRET_KEY", "change-this-secret-key")
    application.config.update(
        MAX_CONTENT_LENGTH=200 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env_str("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes", "on"},
    )
    application.register_error_handler(Exception, application_service.log_unhandled_exception)
    application.before_request(application_service.open_request_db_session)
    application.before_request(application_service.require_login)
    application.teardown_request(application_service.close_request_db_session)
    for blueprint in BLUEPRINTS:
        application.register_blueprint(blueprint)
    return application


app = create_app()


def run_development_server() -> None:
    application_service.ensure_storage()
    port = env_int("PORT", 5000, minimum=1, maximum=65535)
    if env_str("DEBUG_HANG_DUMP", "0") == "1":
        faulthandler.dump_traceback_later(10, repeat=True)

    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    with make_server(
        "127.0.0.1",
        port,
        app,
        server_class=ThreadingWSGIServer,
        handler_class=WSGIRequestHandler,
    ) as server:
        print(f"Serving on http://127.0.0.1:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    run_development_server()
