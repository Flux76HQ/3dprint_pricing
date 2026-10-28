FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    WEB_PORT=6080

WORKDIR /app

# LibreOffice turns the Word invoice template into the PDF invoice (headless, no screen); the fonts are the ones the sample template
# uses (Open Sans, vendored with its licence) so the PDF looks like the Word file. `fontconfig` lets LibreOffice find them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer-nogui fontconfig fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/app/fonts/OpenSans-Regular.ttf backend/app/fonts/OpenSans-Bold.ttf /usr/local/share/fonts/opensans/
RUN fc-cache -f

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The commit is passed at build time (CI: github.sha) and shown next to the version in the sidebar.
ARG GIT_COMMIT=dev
ENV APP_COMMIT=$GIT_COMMIT

COPY backend/app ./app
COPY backend/wsgi.py backend/migrate.py backend/announce_release.py backend/backup_db.py ./
COPY frontend ./static
COPY VERSION ./VERSION
# So the keys can be generated without Python on the host: docker compose run --rm --no-deps app python generate_vapid.py
COPY scripts/generate_vapid.py ./generate_vapid.py
COPY deploy/entrypoint.sh deploy/migrate_uploads.sh /

# The entrypoint starts as root only to fix ownership of the mounted /data, then drops to `app`.
RUN useradd --system --uid 10001 app && chmod +x /entrypoint.sh /migrate_uploads.sh && mkdir -p /data/uploads /data/db && chown -R app:app /data

EXPOSE 6080

# Liveness only; /readyz additionally checks the database.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['WEB_PORT'], timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
