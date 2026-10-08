# Stage 9 - Frontend foundation

Status: planned. Start from the merged Stage 8b baseline.

Estimate: 2 person-days.

This file is the detailed implementation contract for Stage 9. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Replace the Stage 0 placeholder with a tested mobile-first client foundation
that can route, apply a persistent theme before first paint, call the completed
API, and reproduce the backend's integer arithmetic exactly.

References:

- `PLAN.md` sections 2, 3, 8, and 9.
- `IMPLEMENTATION.md` Gate G9 and acceptance checks 9 and 14.
- The Stage 3-8 OpenAPI schema exposed by the running backend.

## Prerequisites and boundaries

- Stage 8b and Gate G8 are merged; the full client-facing API is the baseline.
- Preserve the existing Svelte 5, Vite, TypeScript, Vitest, Svelte Testing
  Library, and Playwright scaffold.
- Add only Tailwind CSS and `svelte-spa-router`, pinned exactly with an updated
  lockfile. Review the resulting dependency tree and run `npm audit` and
  `npm ls`; do not add a theme, request, state, validation, icon, or component
  library.
- `idb` and all draft/synchronization state belong to Stage 11.
- Authentication forms and feature data screens belong to Stage 10. Stage 9
  may use a test-only browser flow to establish a session for API-helper proof.

## Scope

- `frontend/index.html`: pre-paint theme bootstrap.
- `frontend/src/App.svelte`: route host and responsive application shell.
- `frontend/src/api.ts`: local API types and focused fetch helpers.
- `frontend/src/lib/numbers.ts`: exact integer and floor-division helpers.
- `frontend/src/lib/theme.ts`: theme resolution and explicit preference writes.
- `frontend/src/routes/`: small route table and placeholder route components.
- `frontend/src/app.css`: Tailwind integration, theme tokens, focus styles, and
  mobile shell rules.
- Existing Vite proxy, unit-test setup, and Playwright harness as needed for the
  real-backend checks.

## Theme contract

- The only themes are `light` and `dark`; apply one class to the document root.
- Store only an explicit user choice in localStorage. On first visit, use the
  system dark preference when available and light otherwise.
- A small inline bootstrap in `index.html` reads the saved value, ignores any
  invalid value, resolves the fallback, and sets the class before application
  CSS paints. Keep its key and values synchronized with `theme.ts` without
  adding generated code.
- Catch localStorage access/write failures and unavailable media-query APIs.
  A blocked preference store must not prevent boot; apply the available fallback
  or explicit choice for this page and report failed preference persistence.
- `theme.ts` exposes resolution, application, and explicit update operations.
  Updating the theme changes the root class and `color-scheme` immediately and
  persists the choice. No backend preference or cross-tab synchronization is
  required.
- Define semantic CSS tokens for page, elevated surface, text, muted text,
  border, primary action, danger, focus, and synchronization status colors.
  Both themes must retain visible focus and readable form/status contrast.

## Routing and shell

- Use hash routes so production needs no SPA rewrite rule.
- Establish stable routes for Home, Catalog, History, and Settings plus a
  not-found route. Feature routes can render clearly labeled placeholders until
  their owning stage.
- Render a single-column mobile shell with a bottom navigation bar and a bounded
  desktop content width. Navigation targets are at least 44 CSS pixels and use
  text labels; route state is exposed through accessible current-page markup.
- Do not render quick-start, resume, repeat, save, finish, or logout controls
  before their owning stages.

## API contract

Keep one small `api.ts` rather than a generated client or service hierarchy:

- Define ordinary TypeScript request/response types matching the completed
  auth, exercise, workout, previous-performance, and statistics schemas. Keep
  nullable members explicit and preserve snake_case at the API boundary.
- Use relative `/api/v1` URLs and same-origin credentials. Browser cookies stay
  HttpOnly and are never read or stored by frontend code.
- Set `Accept: application/json`. Every mutating request sets
  `Content-Type: application/json`, including bodyless logout and DELETE, because
  the backend checks the header on all mutating verbs. Let the browser supply
  `Origin`; bodyless 204 responses are handled without JSON parsing.
- Add query parameters through `URLSearchParams`, including the backend's exact
  `pageSize`, `date_from`, `date_to`, `muscle_group`, and `equipment` names.
- Parse non-success responses into a typed problem shape carrying status, code,
  safe detail, request ID, validation errors, and current revision when present.
  Preserve `Retry-After` for callers; validation entries use `field` and
  `message`, and response pagination uses `page_size` despite query `pageSize`.
  Preserve an explicit fallback for malformed/non-JSON gateway responses
  without exposing submitted credentials or payloads.
- Distinguish HTTP failures from network/abort failures. Do not retry mutations,
  cache reads, redirect on 401, or implement synchronization policy in this
  layer.
- Accept an `AbortSignal` where callers can supersede reads. Keep endpoint
  helpers explicit enough that request method, path, and body are visible.

## Integer helpers

- Perform domain arithmetic with `bigint`; do not use floating-point
  intermediates.
- Implement floor division with remainder correction because BigInt division
  truncates toward zero. A zero denominator returns `null` where the product
  contract calls for an unavailable result.
- Validate numeric operands with `Number.isSafeInteger` before BigInt conversion,
  and bound every arithmetic intermediate as the backend does, including products
  before division even when the final quotient would fit. BigInt precision does
  not waive the shared safe-range contract.
- Check every conversion back to `number` against
  `Number.MIN_SAFE_INTEGER..Number.MAX_SAFE_INTEGER`; reject unsafe results
  rather than rounding them.
- Mirror the documented calculation order for bodyweight contribution,
  split-weight multiplication, effective load, volume, and signed deltas while
  preserving `null` versus known zero.
- Frontend tests read `tests/fixtures/numeric_examples.json` directly; do not
  copy fixture values or add a generator/shared package.

## Verification

Unit/component tests cover:

- Positive and negative floor division, zero denominator, safe-range edges,
  unsafe conversion rejection, null propagation, and every shared numeric
  fixture.
- Saved light/dark choice, invalid stored values, system-dark selection, light
  fallback, blocked storage/media APIs, root-class replacement, and explicit
  persistence. Cover unsafe operands and intermediate products in numeric tests.
- Route rendering, current navigation state, not-found handling, minimum shell
  semantics, and keyboard-visible navigation.
- API URL/query construction, JSON and 204 success, problem+json parsing,
  malformed error fallback, credentials/header behavior, abort/network errors,
  and strict separation between transport and retry policy.

Playwright uses the existing isolated real backend to prove that the production
build loads with the selected theme already on the root element, routing works,
and API helpers can register/login and perform an authenticated read through the
Vite `/api` proxy. Keep credentials and created data test-local.

Before adding authenticated E2E, extend `playwright.config.ts` to run migrations
on its disposable database before API startup, explicitly set `APP_ORIGIN` to the
frontend test origin and `COOKIE_SECURE=false` for local HTTP, and disable reuse
of existing servers for both processes. The current health-only scaffold neither
migrates nor configures the test origin; inheriting development settings or
reusing a listener would invalidate isolation and CSRF checks. Verify at least
one real browser mutation, not only Playwright's separate HTTP request client.

Run:

```bash
cd frontend
npm run check
npm run lint
npm run test:unit
npm run build
npm run test:e2e
npm ls
npm audit
```

## Non-goals

- Login/register UI, route authorization, feature screens, or server data
  caching.
- IndexedDB, drafts, save coordination, offline app startup, or service workers.
- Runtime response-schema validation, generated clients, and shared backend/
  frontend packages.
- A user-facing theme switch; Stage 13 places that control in Settings.

## Gate G9

G9 passes when the production client shell routes correctly, theme selection is
applied before first paint and persists through the shared theme module, API
helpers authenticate and call the live test backend, frontend arithmetic matches
all shared backend fixtures, and all frontend checks are green locally and in
CI.

Completion evidence and the Stage 10 marker must be recorded in
`IMPLEMENTATION.md` in the Stage 9 branch before merge.

## Completion evidence

Not yet implemented. Record the branch, dependency review, changed public
surface, commands/results, test counts, browser observations, and Gate G9
acceptance mapping here before merge.
