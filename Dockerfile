FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    APP_ENV=production

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fonts-liberation \
        libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements_optional_parsers.txt requirements-prod.txt ./
ARG INSTALL_OPTIONAL_PARSERS=0
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-prod.txt \
    && if [ "$INSTALL_OPTIONAL_PARSERS" = "1" ]; then python -m pip install -r requirements_optional_parsers.txt; fi \
    && python -m playwright install --with-deps chromium \
    && rm -rf /root/.cache/pip

COPY . .

RUN mkdir -p data logs exports feeds storage/file-import \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=5).read()" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
