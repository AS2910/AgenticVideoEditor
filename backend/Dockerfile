# Voltage backend (FastAPI) and worker. Built from the repo root, because the
# Help articles live in ../help (app/help reads <repo>/help/articles):
#   docker build -f backend/Dockerfile -t voltage-backend .
# API:    the default command (uvicorn on :8000).
# Worker: python -m app.worker (the same image; see docker-compose.yml).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AVE_DATA_DIR=/data \
    PYTHONPATH=/srv/backend

# ffmpeg (with ffprobe and libass, so captions in any script use the subtitles
# filter) and the sqlite3 shell for `.backup` (scripts/backup.sh).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg sqlite3 curl \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 voltage \
 && useradd --system --uid 10001 --gid voltage --home-dir /srv --shell /usr/sbin/nologin voltage

WORKDIR /srv/backend

# Dependencies first (cached until pyproject.toml changes): install the
# package from a stub so only the dependency layer is built here.
COPY backend/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install . && rm -rf app build *.egg-info

# The source. The app runs from this tree (PYTHONPATH), not from site-packages:
# it finds bench/rungs.json and ../help/articles relative to its own files,
# and those are not package data.
COPY backend/app ./app
COPY backend/bench ./bench
COPY help /srv/help
# OPS.md: backup.sh and restore.sh, run with `docker compose exec -T app /srv/scripts/backup.sh /data /data/backups`.
COPY scripts /srv/scripts
RUN pip install --no-deps . && rm -rf build *.egg-info \
 && mkdir -p /data \
 && chown -R voltage:voltage /data

USER voltage
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health > /dev/null || exit 1

# One process: jobs run on threads inside it, so never more than one worker
# process per data dir. --proxy-headers trusts X-Forwarded-* from the web
# container (nginx) in front of it.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
