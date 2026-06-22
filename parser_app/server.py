"""Local production-like threaded WSGI server entry point."""

import faulthandler
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from parser_app import app, ensure_storage
from parser_app.runtime import env_int, env_str


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def run() -> None:
    ensure_storage()
    port = env_int("PORT", 5000, minimum=1, maximum=65535)
    if env_str("DEBUG_HANG_DUMP", "0") == "1":
        faulthandler.dump_traceback_later(10, repeat=True)

    with make_server(
        "127.0.0.1",
        port,
        app,
        server_class=ThreadingWSGIServer,
        handler_class=WSGIRequestHandler,
    ) as server:
        print(f"Serving on http://127.0.0.1:{port}", flush=True)
        server.serve_forever()
