FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TMPDIR=/tmp/parser \
    PORT=5000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && mkdir -p /tmp/parser /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin/temp \
    && chmod -R 1777 /tmp/parser \
    && chmod -R a+rwX /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin \
    && python -m playwright install --with-deps chromium chromium-headless-shell

COPY . .
RUN mkdir -p data logs exports feeds storage/file-import \
    && chmod +x deploy/docker-entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["deploy/docker-entrypoint.sh"]
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "app:app"]
