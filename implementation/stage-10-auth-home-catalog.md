# Stage 10 - Auth, Home, and Catalog

Status: planned. Start after Gate G9 is merged.

Estimate: 2.5 person-days.

This file is the detailed implementation contract for Stage 10. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Deliver the first complete signed-in browser flow: register or log in, navigate
the authenticated shell, inspect read-only Home summaries, and manage the
caller's custom exercise catalog.

References:

- `PLAN.md` sections 4, 6, 7, and 8.
- `IMPLEMENTATION.md` Gate G10.
- Stage 9's API, theme, routing, and shell contracts.

## Scope and boundaries

- Add `features/auth`, `features/home`, `features/catalog`, and their routes.
- Keep authentication state in a small Svelte module initialized from
  `GET /auth/me`; do not add a state-management dependency.
- Home is read-only in this stage. It shows active workout summaries, recent
  finished workouts, and the current local week's statistics.
- Catalog supports search, muscle/equipment filters, stable paging, default/
  custom labels, custom creation, and editing of the caller's custom entries.
- Do not expose quick start, resume, repeat-last, catalog picking into a workout,
  history detail navigation, deletion, draft-safe reauthentication, or logout.
  Their owning stages are 12a-12c and 13.
- No new dependency is expected.

## Authentication flow

- On application startup, call `GET /auth/me` once. A 200 establishes the user;
  a 401 establishes an anonymous state; network/server failures render a retry
  state rather than pretending the user is logged out.
- Anonymous feature routes lead to login while preserving the requested route
  in memory for the current page load. Authenticated visits to auth routes lead
  to Home.
- Registration collects email, password, and optional display name. A successful
  registration does not imply a session; present a clear success state and move
  to login with the normalized email available for convenience.
- Login stores no credential or token in frontend persistence. On success, set
  the returned public user as current and navigate to the intended route/Home.
- A 401 from a protected read invalidates signed-in state and pauses other reads;
  login rejection remains a form error. Guard auth and panel responses by request
  identity so a superseded request cannot restore a stale user or another user's
  data. Stage 11 adds a local-only recovery state without treating cached identity
  as an authenticated session.
- Show generic invalid-credential behavior from the API without trying to infer
  whether an account exists. Map field validation by path where possible and
  preserve a form-level fallback for conflict, throttling, network, and server
  failures.
- Disable only the submitted action while a request is active, prevent duplicate
  submits, use real labels and autocomplete attributes, and return focus to a
  useful heading/error after navigation or failure.

## Home reads

Issue independent, abortable reads so one failed panel does not erase the
others:

- Active workouts: `GET /workouts?status=active` with a bounded first page.
- Recent history: `GET /workouts?status=finished` with a bounded first page.
- Weekly summary: derive the caller's current local calendar date from the
  current instant plus `utc_offset_minutes`, calculate Monday through Sunday,
  and request `GET /stats/summary` with both dates. Use date-only integer/
  calendar operations that do not depend on the browser's local timezone.
  Both API date bounds are inclusive; the server converts them to a half-open
  instant range. Display times using this same profile offset, not browser-local
  formatting, and refresh the weekly range on foreground return across a week.

Render explicit loading, empty, error/retry, and populated states. Show integer
counts and volume with fixed metric labels; when volume is incomplete, expose
the unknown count and never label the known partial sum as complete. The streak
is full-history even though the other values use the weekly range. Active and
recent cards are informational only in Stage 10.

## Catalog behavior

- Search and filters are explicit controlled inputs. Debounced search may
  reduce requests, but each superseded read is aborted and stale responses are
  ignored by request identity.
- Keep filters in the route query/hash state when the router supports it without
  a second state layer. Reset paging when a filter changes.
- Render all server enum values through local human-readable labels while
  preserving exact API literals. Clearly mark defaults and custom entries.
- Default entries have no edit action. Editing a custom entry starts from its
  current complete values and sends a PATCH containing only changed fields.
- Creation and editing use handwritten checks for immediate required/range/
  cross-field feedback. The backend remains authoritative, including duplicate
  names, bodyweight percentage rules, and split-weight side count.
- After a successful mutation, update/refetch the affected visible page without
  duplicating or reordering entries locally in a way that disagrees with the
  server's stable ordering.
- Catalog deletion remains out of this screen's Stage 10 scope; it is not needed
  for the gate and avoiding it keeps confirmation/in-use recovery out of this
  increment.

## Mobile and accessibility rules

- Use single-column forms and lists at phone widths, bounded readable layouts on
  desktop, 44 CSS pixel action targets, visible labels, and keyboard-operable
  filters/dialogs.
- Validation and request errors use text in addition to color and are associated
  with fields or announced at form level.
- Do not use placeholder text as the only label. Preserve visible focus in both
  Stage 9 themes.
- Numeric catalog fields use integer steps and numeric input mode, reject
  fractional/string coercion before request construction, and stay inside the
  API bounds.

## Verification

Component tests cover:

- Startup auth states, protected-route behavior, register-then-login semantics,
  duplicate/invalid/throttled credentials, network retry, and session expiry or
  account change while protected reads are in flight.
- Home panel loading/error isolation, empty data, active/recent rendering,
  fixed-offset Monday/Sunday range construction, known-zero versus unknown/
  partial volume, and metric labels.
- Catalog search/filter/page query construction, stale-response suppression,
  default/custom actions, enum labels, create/edit validation, backend problem
  display, and successful refresh.

Playwright against the isolated backend covers registration, explicit login,
authenticated navigation, seeded default browsing, search/filtering, custom
creation and editing, and Home active/recent/weekly empty and populated states.
No test reaches into the database or uses a reset endpoint.

Run the complete frontend gate:

```bash
cd frontend
npm run check
npm run lint
npm run test:unit
npm run build
npm run test:e2e
```

## Non-goals

- Workout creation/editor actions, IndexedDB, synchronization, or offline
  recovery.
- Full history/detail, Settings, logout, or reauthentication over a draft.
- Catalog deletion, default-entry mutation, batch operations, or client-side
  read caching.

## Gate G10

G10 passes when a new user can register, explicitly log in, navigate the
authenticated shell, view correctly grouped read-only Home summaries, browse
and filter the visible catalog, and create/edit private custom entries through
accessible mobile layouts, with component and real-backend Playwright coverage
green locally and in CI.

Completion evidence and the Stage 11a marker must be recorded in
`IMPLEMENTATION.md` in the Stage 10 branch before merge.

## Completion evidence

Not yet implemented. Record the branch, changed UI/API surface, commands and
test counts, browser/mobile observations, and Gate G10 evidence here before
merge.
