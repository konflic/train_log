# BaseFit

Mobile-first fitness training tracker: log exercises, sets, reps, and weights.
Metric units only (whole kilograms). See [PLAN.md](PLAN.md) for the product
contract, [IMPLEMENTATION.md](IMPLEMENTATION.md) for the staged build plan, and
[AGENTS.md](AGENTS.md) for repository-wide development rules.

## Layout

```text
backend/    FastAPI + SQLite (stdlib sqlite3, synchronous, direct SQL)
frontend/   Svelte 5 + Vite + TypeScript SPA
```

## Prerequisites

- Python 3.12.3 (`python3`)
- Node.js 24.19.0 and npm
- Chromium for Playwright E2E: `cd frontend && npx playwright install chromium`

## Backend setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -c constraints.txt -e '.[dev]'
```

`backend/constraints.txt` pins the complete resolved Python environment; update
it deliberately whenever a dependency changes.

Run the API for local development (listens on port 8000; the frontend dev and
preview servers proxy `/api` there):

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload
```

Backend checks:

```bash
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app migrate.py
.venv/bin/pytest -q
```

## Database migrations and backups

Migrations are numbered SQL files in `backend/migrations/` and are run
explicitly before serving requests (never per worker). `migrate.py` honors
`DATABASE_PATH` (default `data/basefit.db`), creates the file with WAL
enabled, applies each pending migration in its own transaction, and is a
no-op when the database is up to date:

```bash
cd backend
.venv/bin/python migrate.py
```

Back up a live database with the online backup API (safe while WAL is
active; never plain-copy the main file) and verify restores:

```bash
cd backend
.venv/bin/python -m app.backup backup data/basefit.db backups/basefit-$(date -u +%Y%m%dT%H%M%SZ).db
.venv/bin/python -m app.backup verify backups/basefit-<timestamp>.db
```

To restore: stop the application, move the live database and its `-wal`/`-shm`
sidecars aside, copy the backup into place, remove any stale sidecars, run
`verify`, then start the application again. Back up before destructive schema
migrations. Database files, WAL sidecars, and backups never enter Git.

## Frontend setup

```bash
cd frontend
npm ci
```

Frontend checks and development:

```bash
cd frontend
npm run check       # svelte-check (TS + Svelte diagnostics)
npm run lint        # eslint + prettier --check
npm run test:unit   # vitest (jsdom)
npm run build       # production build
npm run dev         # dev server on http://localhost:5173
```

## E2E smoke tests

Playwright starts, waits for, and tears down both servers itself:

- backend: `uvicorn` on port 8123 with an isolated temporary `DATABASE_PATH`
- frontend: production build served by `vite preview` on port 4173, proxying
  `/api` to the backend

```bash
cd frontend
npm run test:e2e
```

The backend Python interpreter is resolved as: `BACKEND_PYTHON` env var, then
`backend/.venv/bin/python`, then system `python3`. Ports can be overridden with
`E2E_BACKEND_PORT` / `E2E_FRONTEND_PORT`.

## Configuration

All configuration is environment variables (see `backend/app/config.py`).
Defaults target local HTTP development; production deployments must set every
variable explicitly.

| Variable              | Default                  | Purpose                                   |
| --------------------- | ------------------------ | ----------------------------------------- |
| `DATABASE_PATH`       | `data/basefit.db`        | SQLite database file location             |
| `SESSION_TTL_SECONDS` | `86400`                  | Login session lifetime                    |
| `APP_ORIGIN`          | `http://localhost:5173`  | Allowed browser origin (CSRF checks)      |
| `COOKIE_SECURE`       | `false`                  | Secure cookie flag; `true` in production  |
| `APP_ENV`             | `development`            | Environment label                         |

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and
push to `master`: backend lint/format/typecheck/tests, frontend
check/lint/unit/build, and Playwright browser smoke tests against a real
backend process. Database, WAL, backup, and `.env` files never enter Git.
