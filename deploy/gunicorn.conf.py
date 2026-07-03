import multiprocessing
import os


bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("WEB_THREADS", "4"))
timeout = int(os.environ.get("WEB_TIMEOUT", "180"))
graceful_timeout = int(os.environ.get("WEB_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("WEB_KEEPALIVE", "5"))
worker_class = "gthread"
accesslog = "-" if os.environ.get("GUNICORN_ACCESS_LOG", "0").lower() in {"1", "true", "yes", "on"} else None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

if workers < 1:
    workers = max(1, min(2, multiprocessing.cpu_count()))
