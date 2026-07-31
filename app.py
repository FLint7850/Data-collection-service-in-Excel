"""Flask application assembly and blueprint registration."""

import faulthandler

from flask import Flask

from routes import BLUEPRINTS
from services import core_service as core


def create_app() -> Flask:
    application = Flask(__name__, static_folder=None)
    application.secret_key = core.env_str("FLASK_SECRET_KEY", "change-this-secret-key")
    application.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    application.register_error_handler(Exception, core.log_unhandled_exception)
    application.before_request(core.open_request_db_session)
    application.before_request(core.require_login)
    application.teardown_request(core.close_request_db_session)
    for blueprint in BLUEPRINTS:
        application.register_blueprint(blueprint)
    return application


app = create_app()


def run_development_server() -> None:
    core.ensure_storage()
    port = core.env_int("PORT", 5000, minimum=1, maximum=65535)
    if core.env_str("DEBUG_HANG_DUMP", "0") == "1":
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
