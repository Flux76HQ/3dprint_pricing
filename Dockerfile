FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    WEB_PORT=6080

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The commit is passed at build time (CI: github.sha) and shown next to the version in the sidebar.
ARG GIT_COMMIT=dev
ENV APP_COMMIT=$GIT_COMMIT

COPY backend/app ./app
COPY backend/wsgi.py backend/migrate.py backend/announce_release.py ./
COPY frontend ./static
COPY VERSION ./VERSION
COPY deploy/entrypoint.sh /entrypoint.sh

# The entrypoint starts as root only to fix ownership of the mounted /data, then drops to `app`.
RUN useradd --system --uid 10001 app && chmod +x /entrypoint.sh && mkdir -p /data/uploads && chown -R app:app /data

EXPOSE 6080

# Liveness only; /readyz additionally checks the database.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['WEB_PORT'], timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
