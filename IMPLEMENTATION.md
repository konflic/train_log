# BaseFit - Further Development Plan

`PLAN.md` is the product contract. This file contains only work that remains
after the completed MVP implementation stages.

## Remaining roadmap

| Stage | Deliverable | Primary verification | Estimate |
|-------|-------------|----------------------|----------|
| 13 | History/detail, Settings, deletion, and account-safe logout | Frontend unit, build, and Playwright gates | 2.5 days |
| 14 | Minimal operational admin panel and audit log | Admin API/security and Playwright | 3 days |
| 15 | Acceptance evidence and production deployment smoke | Full CI, deployment, and restart checks | 4 days |

## Stage 13 - History, Settings, and logout

Detailed contract: [`implementation/stage-13-history-settings-logout.md`](implementation/stage-13-history-settings-logout.md).

Implement the remaining user-facing Phase 1 features:

- Finished-workout history and read-only detail with previous-performance comparisons.
- Settings for theme, display name, bodyweight, UTC offset, and logout.
- Revision-checked deletion with recovery for conflicts and uncertain responses.
- Logout that synchronizes or explicitly discards all account-local pending work.
- Cross-tab and account-switch protection for drafts, pending requests, and delayed responses.

Gate G13 completes Milestone C when history, settings, deletion, logout, theme
legibility, account isolation, and the frontend verification suite pass.

## Stage 14 - Minimal operational admin panel

Implement the limited account administration defined by `PLAN.md`:

- Add role/status fields and an append-only administrative audit log through a
  numbered migration that preserves existing data.
- Add a confirmation-based bootstrap CLI with last-active-admin safeguards.
- Resolve role and account status on every authenticated request; disabled
  accounts cannot log in or use existing sessions.
- Add bounded user and audit reads plus disable, enable, and session-revocation
  actions with reauthentication, CSRF protections, confirmation, and reasons.
- Add the role-gated admin UI without impersonation, password controls, workout
  access, user deletion, or default-catalog editing.

Gate G14 requires migration preservation, authorization, disabled-session
rejection, atomic account controls, safe audit content, and the complete admin
browser flow.

## Stage 15 - Acceptance evidence and production deployment smoke

Complete the Phase 1 ship gate:

- Audit all 15 acceptance checks and close genuine coverage gaps.
- Verify same-origin SPA/API serving, explicit migrations, persistent SQLite,
  backup/restore, and restart persistence.
- Run isolated disposable remote E2E databases; production must expose no
  fixture or reset endpoints.
- Smoke HTTPS cookies, authentication, create/save/finish, restart, and data
  persistence using the production artifact.
- Record mobile, keyboard, light/dark theme, and UTC-offset observations.
- Document setup, deployment, migrations, backups, admin bootstrap, account
  controls, session revocation, and audit review.

Gate G15 passes when every acceptance check has evidence, production smoke is
successful, isolated E2E cleanup is verified, and operating documentation is
complete.

## Later, when justified

These are product-level follow-up plans, not part of the remaining Phase 1
implementation stages:

- Phase 2 progression features, optional PWA app-shell caching, and finished-
  workout editing through the existing revisioned save protocol.
- Phase 3 bodyweight history, dedicated statistics, charts, calendar views, and
  documented approximate calorie estimates.
- Native client support, PostgreSQL/scaling work, offline creation, background
  sync, automatic merging, imports, media, sharing, and notifications.

All future work remains subject to the permanent metric-only and integer-only
product rules in `PLAN.md`.
