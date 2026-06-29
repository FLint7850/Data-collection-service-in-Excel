import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:5000")
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
if workers != 1:
    raise RuntimeError(
        "Для этого проекта нужен ровно один worker-процесс: "
        "сканы, очередь и планировщик хранятся в памяти приложения. "
        "Масштабируйте потоками, а не worker-процессами."
    )

worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "60"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))
worker_tmp_dir = os.environ.get("GUNICORN_WORKER_TMP_DIR", "/dev/shm")

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True
enable_stdio_inheritance = True

# Не включаем max_requests: внезапная перезагрузка worker может оборвать активный сбор.
