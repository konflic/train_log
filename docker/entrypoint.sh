#!/bin/sh
# Container entrypoint: apply migrations explicitly before the API starts
# (never per worker), then serve the SPA and API from one uvicorn process.
set -eu

echo "basefit: applying migrations to ${DATABASE_PATH}"
python migrate.py

echo "basefit: starting API on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
