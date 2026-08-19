FROM node:24-bookworm-slim AS codex-cli

ARG CODEX_CLI_VERSION=0.146.0
RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}" \
    && mkdir -p /opt/botasaurus-js \
    && npm install --prefix /opt/botasaurus-js proxy-chain@3.0.0 botasaurus-controls@6.0.66 \
    && npm cache clean --force

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

COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/bin/codex /usr/local/bin/codex
COPY --from=codex-cli /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex
COPY --from=codex-cli /opt/botasaurus-js /opt/botasaurus-js

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && mkdir -p /usr/local/lib/python3.11/site-packages/javascript_fixes/js/node_modules \
    && ln -s /opt/botasaurus-js/node_modules/proxy-chain /usr/local/lib/python3.11/site-packages/javascript_fixes/js/node_modules/proxy-chain \
    && ln -s /opt/botasaurus-js/node_modules/botasaurus-controls /usr/local/lib/python3.11/site-packages/javascript_fixes/js/node_modules/botasaurus-controls \
    && rm -rf /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin/temp \
    && mkdir -p /tmp/parser /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin \
    && chmod -R 1777 /tmp/parser \
    && chmod -R a+rwX /usr/local/lib/python3.11/site-packages/botasaurus_requests/bin \
    && python -c "import botasaurus_requests.cffi" \
    && python -m playwright install --with-deps chromium chromium-headless-shell

# Docker COPY dereferences the npm launcher symlink. Restore it so Node resolves
# the platform-specific @openai/codex package next to the JS entry point.
RUN ln -sf ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

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
