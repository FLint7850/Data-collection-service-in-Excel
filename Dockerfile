FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TMPDIR=/tmp/parser \
    PORT=5000

WORKDIR /app

ARG DEBIAN_MIRROR=https://mirror.yandex.ru

RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && rm -rf /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin/temp \
    && mkdir -p /tmp/parser /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin \
    && chmod -R 1777 /tmp/parser \
    && chmod -R a+rwX /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin \
    && python -m playwright install --with-deps chromium chromium-headless-shell

FROM base AS test
COPY . .
RUN pip install pyflakes==3.4.0 \
    && python -m pyflakes app.py config.py models.py api_dto.py progress_tracker.py query_utils.py database routes runtime services test \
    && python -m unittest discover -s test -v \
    && python -m compileall -q app.py config.py database routes runtime services

FROM base AS runtime
COPY --from=test /app /app
RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /app app \
    && mkdir -p data exports feeds storage/file-import storage/price-converter profiles/projects \
    && chown -R app:app /app /ms-playwright /tmp/parser \
    && chmod +x deploy/docker-entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["deploy/docker-entrypoint.sh"]
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "app:app"]
