FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    WEB_PORT=6080

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/wsgi.py backend/migrate.py ./
COPY frontend ./static
COPY VERSION ./VERSION
COPY deploy/entrypoint.sh /entrypoint.sh

RUN useradd --system --uid 10001 app && chmod +x /entrypoint.sh
USER app

EXPOSE 6080

# Liveness only; /readyz additionally checks the database.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['WEB_PORT'], timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
