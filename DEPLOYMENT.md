# BaseFit deployment

Container packaging for testing and real-host deployment. One image serves
the built SPA and `/api/v1` under a **single origin** with **one API
process** and a **persistent local-disk SQLite database**; migrations run
explicitly in the entrypoint before the server starts (PLAN.md §2, §5).

Containers are packaging, not a runtime requirement: everything below also
works with a plain `python -m uvicorn` + static directory setup (see
README.md).

## Layout

```text
Dockerfile              multi-stage: node build of the SPA + python runtime
docker/entrypoint.sh    migrate.py, then uvicorn on 0.0.0.0:8000
docker/smoke.sh         public-API-only deployment smoke check
docker-compose.yml      real-host stack (persistent volume, production env)
docker-compose.test.yml disposable test stack (tmpfs database, local HTTP)
.env.example            template for real-host configuration
```

The backend serves the SPA when `STATIC_DIR` points at the built `dist`
directory. Unknown non-API paths return plain 404s; unknown `/api/v1/*` paths
keep the problem+json contract. The frontend uses hash routes, so no SPA
rewrite rule is needed.

## Build

```bash
docker build -t basefit .
```

The build context excludes databases, `.env` files, and local caches
(`.dockerignore`). The production `npm run build` never includes the e2e-only
API hook.

## Disposable test instance (local or on-server QA)

Test reset means replacing the whole disposable database, never deleting rows
from a mixed one. The test stack keeps the database on tmpfs, so stopping the
container destroys it:

```bash
docker compose -f docker-compose.test.yml up --build -d
docker/smoke.sh http://127.0.0.1:8080
docker compose -f docker-compose.test.yml down   # database destroyed
```

It runs with `APP_ENV=test` and `COOKIE_SECURE=false` for local HTTP on
`127.0.0.1:8080` (override with `BASEFIT_TEST_PORT`). Point automated or
human QA at instances like this one — **never** at the production database.
Production, human QA/beta, and automated E2E stay separate instances with
separate origins, processes, SQLite files, and backup locations even when
they share one server and the same built artifact.

## Real-host deployment

Prerequisites: Docker with the compose plugin, and a reverse proxy that
terminates TLS (the API refuses to start with a non-Secure cookie outside
local `development`/`test` environments, so any remote origin must be HTTPS).

1. Copy the repository (or just the build context) to the host and configure:

   ```bash
   cp .env.example .env
   # set at least APP_ORIGIN to the exact public origin, e.g.
   # APP_ORIGIN=https://fit.example.com
   ```

   `APP_ORIGIN` must match the browser origin exactly, including scheme: the
   CSRF middleware rejects every mutating request whose `Origin` header
   differs.

2. Build and start:

   ```bash
   docker compose up -d --build
   docker compose ps          # healthcheck should report healthy
   ```

   The container binds `127.0.0.1:8000` on the host by default
   (`BASEFIT_BIND`). Data persists in the `basefit-data` named volume.

3. Reverse proxy (example for nginx; any TLS proxy works). No SPA rewrite
   rules are needed — everything is same-origin:

   ```nginx
   server {
       listen 443 ssl;
       server_name fit.example.com;
       # ssl_certificate / ssl_certificate_key ...

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }
   }
   ```

4. Smoke the deployment through the public API only. For production use one
   clearly named reusable synthetic account (`SMOKE_EMAIL`/`SMOKE_PASSWORD`);
   the smoke tolerates its registration conflict and never runs broad cleanup:

   ```bash
   SMOKE_EMAIL=deploy-smoke@your-domain SMOKE_PASSWORD=... \
     docker/smoke.sh https://fit.example.com
   ```

   The smoke covers health, SPA serving, register/login mutations with the
   Origin check, an authenticated read, and rejection of a foreign Origin.

## Upgrades and restarts

```bash
git pull                       # or copy the new build context
docker compose up -d --build   # entrypoint migrates before serving
```

To replace the database while redeploying the configured remote host, run from
this repository:

```bash
./redeploy.sh
```

It pulls `master`, removes the Compose volumes (including the SQLite database),
and rebuilds the stack. Override `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_DIR`, or
`SSH_KEY` only when deploying another host.

Migrations are numbered, transactional, and refuse databases recorded by
newer code, so a restart with the previous image after a failed upgrade is
safe only if no newer migration ran. Back up before destructive schema
migrations. Session data survives restarts (database-backed sessions); the
in-memory login throttle intentionally resets.

## Backups and restore

Use the online backup API (WAL-safe; never plain-copy the live file):

```bash
docker compose exec basefit python -m app.backup backup \
  /data/basefit.db /data/basefit-backup.db
docker compose cp basefit:/data/basefit-backup.db ./backups/
docker compose exec basefit python -m app.backup verify /data/basefit-backup.db
```

Restore: stop the application, move the live database and its `-wal`/`-shm`
sidecars aside, copy the backup into the volume at `DATABASE_PATH`, remove
stale sidecars, verify, then start again. See README.md for details.

## Configuration reference

| Variable              | Container default   | Purpose                                    |
| --------------------- | ------------------- | ------------------------------------------ |
| `DATABASE_PATH`       | `/data/basefit.db`  | SQLite file on the mounted volume          |
| `STATIC_DIR`          | `/app/static`       | Built SPA directory (`""` disables)        |
| `APP_ORIGIN`          | — (required in `.env`) | Allowed browser origin for CSRF checks  |
| `COOKIE_SECURE`       | `true`              | Must stay true for any remote origin       |
| `SESSION_TTL_SECONDS` | `86400`             | Login session lifetime                     |
| `APP_ENV`             | `production`        | Environment label                          |
| `PORT`                | `8000`              | Listen port inside the container           |
