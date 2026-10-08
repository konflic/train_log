# syntax=docker/dockerfile:1
#
# BaseFit single-container image: the built SPA and the API are served under
# one origin by one API process (PLAN.md §2, Stage 15). Migrations run
# explicitly in the entrypoint before the server starts; the SQLite database
# lives on a mounted volume under /data.

# --- Frontend build --------------------------------------------------------
FROM node:24.19.0-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
# Production mode: the e2e-only API hook is statically dropped from this build.
RUN npm run build

# --- Runtime ----------------------------------------------------------------
FROM python:3.12.3-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/basefit.db \
    STATIC_DIR=/app/static

WORKDIR /app

# Install the backend from its pinned constraint set (runtime deps only).
COPY backend/pyproject.toml backend/constraints.txt ./
COPY backend/app ./app
COPY backend/migrate.py ./
COPY backend/migrations ./migrations
RUN pip install --no-cache-dir -c constraints.txt .

# Built SPA served by the same process under one origin.
COPY --from=frontend-build /build/dist ./static

COPY docker/entrypoint.sh ./entrypoint.sh

# Non-root runtime user; the database volume is owned by it.
RUN useradd --create-home --uid 10001 basefit \
    && mkdir -p /data \
    && chown basefit:basefit /data \
    && chmod +x /app/entrypoint.sh
USER basefit

EXPOSE 8000

# stdlib-only health probe (slim images ship without curl/wget).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"

ENTRYPOINT ["/app/entrypoint.sh"]
