<script lang="ts">
  import ActionIcon from './components/ActionIcon.svelte';
  import Router, { replace, router } from 'svelte-spa-router';
  import LoginRoute from './features/auth/LoginRoute.svelte';
  import RegisterRoute from './features/auth/RegisterRoute.svelte';
  import {
    rememberIntendedRoute,
    session,
  } from './features/auth/session.svelte';
  import CatalogRoute from './features/catalog/CatalogRoute.svelte';
  import HomeRoute from './features/home/HomeRoute.svelte';
  import TrainingPlansRoute from './features/plans/TrainingPlansRoute.svelte';
  import { initializeTheme } from './lib/theme';
  import { initializeLocale } from './lib/i18n';
  import HistoryRoute from './routes/HistoryRoute.svelte';
  import WorkoutDetailRoute from './routes/WorkoutDetailRoute.svelte';
  import NotFoundRoute from './routes/NotFoundRoute.svelte';
  import SettingsRoute from './routes/SettingsRoute.svelte';
  import WorkoutRoute from './features/workout/WorkoutRoute.svelte';
  import SessionChooser from './features/workout/SessionChooser.svelte';
  import { activeSession } from './features/workout/activeSession.svelte';

  // Hash route table: production serving needs no SPA rewrite rule. Feature
  // routes render clearly labeled placeholders until their owning stage.
  const routes = {
    '/': HomeRoute,
    '/catalog': CatalogRoute,
    '/history': HistoryRoute,
    '/history/:id': WorkoutDetailRoute,
    '/settings': SettingsRoute,
    '/training-plans': TrainingPlansRoute,
    '/workouts/start': SessionChooser,
    '/workouts/current': WorkoutRoute,
    '/workouts/:id': WorkoutRoute,
    '/login': LoginRoute,
    '/register': RegisterRoute,
    '*': NotFoundRoute,
  };

  // Bottom navigation stays icon-only while retaining named, 44-pixel targets.
  const navItems: ReadonlyArray<{
    path: string;
    label: string;
    icon: 'home' | 'catalog' | 'history' | 'settings' | 'workout';
  }> = [
    { path: '/', label: 'Home', icon: 'home' },
    { path: '/catalog', label: 'Catalog', icon: 'catalog' },
    {
      path: '/workouts/start',
      label: 'Start workout session',
      icon: 'workout',
    },
    { path: '/history', label: 'History', icon: 'history' },
    { path: '/settings', label: 'Settings', icon: 'settings' },
  ];

  const authPaths = new Set(['/login', '/register']);

  // The inline bootstrap in index.html already applied the theme before
  // first paint; applying it again keeps direct mounts (tests, HMR)
  // consistent with the shared theme module.
  initializeTheme();
  initializeLocale();

  // Resolve the session once at startup from GET /auth/me.
  void session.initialize();

  function isCurrentPage(path: string): boolean {
    const current = router.location;
    if (path === '/workouts/start') return current.startsWith('/workouts/');
    return path === '/'
      ? current === '/'
      : current === path || current.startsWith(`${path}/`);
  }

  // Render routes only when they may be shown: authenticated anywhere, or
  // anonymous on the auth routes. Anonymous feature visits redirect to login
  // while preserving the requested route for this page load; authenticated
  // visits to auth routes lead to Home.
  const isAuthPath = $derived(authPaths.has(router.location));
  const routerReady = $derived(
    session.status === 'authenticated' ||
      (session.status === 'anonymous' && isAuthPath),
  );
  const showChrome = $derived(routerReady && !isAuthPath);

  $effect(() => {
    const path = router.location;
    // Anonymous feature routes lead to login while preserving the requested
    // route (including its query) for this page load. Authenticated visits to
    // auth routes are redirected by the auth routes themselves, which avoids
    // racing the post-login navigation. `replace` keeps history clean and
    // updates the router state synchronously.
    if (session.status === 'anonymous' && !authPaths.has(path)) {
      const querystring = router.querystring;
      if (session.logoutRequested) {
        void replace('/login').then(() => {
          session.logoutRequested = false;
        });
        return;
      }
      rememberIntendedRoute(querystring ? `${path}?${querystring}` : path);
      void replace('/login');
    }
  });

  $effect(() => {
    const accountId = session.user?.id;
    if (session.status === 'authenticated' && accountId) {
      void activeSession.refresh(accountId);
    } else if (session.status === 'anonymous') {
      activeSession.reset();
    }
  });

  const workoutPath = $derived(
    activeSession.workoutId === null
      ? '/workouts/start'
      : `/workouts/${activeSession.workoutId}`,
  );

  function navPath(path: string): string {
    return path === '/workouts/start' ? workoutPath : path;
  }

  function navLabel(path: string, label: string): string {
    if (path !== '/workouts/start') return label;
    if (activeSession.workoutId !== null) return 'Resume active session';
    if (activeSession.status === 'loading') return label;
    if (activeSession.status === 'error') return 'Retry workout session check';
    return label;
  }

  function retryActiveSession(event: MouseEvent, path: string): void {
    if (path !== '/workouts/start' || activeSession.status !== 'error') return;
    const accountId = session.user?.id;
    if (!accountId) return;
    event.preventDefault();
    void activeSession.refresh(accountId);
  }
</script>

<svelte:window
  onfocus={() => {
    if (session.user) void activeSession.refresh(session.user.id);
  }}
/>

<div class="flex min-h-dvh flex-col">
  <main
    id="app-main-content"
    class={showChrome
      ? 'mx-auto w-full max-w-2xl flex-1 px-4 pt-4 pb-4'
      : 'mx-auto flex w-full max-w-sm flex-1 items-center px-4 py-8'}
  >
    {#if session.status === 'loading'}
      <p role="status">Checking your session…</p>
    {:else if session.status === 'error'}
      <h1 tabindex="-1">Cannot reach the server</h1>
      <p class="mt-2 text-muted">
        Your session could not be checked, so you were not signed out, retry
        when the connection is back
      </p>
      <button
        type="button"
        class="mt-4 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
        onclick={() => void session.initialize()}
      >
        Retry
      </button>
    {:else if routerReady}
      <Router {routes} />
    {:else}
      <p role="status">Redirecting to login…</p>
    {/if}
  </main>
  {#if showChrome}
    <nav
      aria-label="Primary"
      class="sticky inset-x-0 bottom-0 shrink-0 border-t border-edge bg-surface"
    >
      <ul class="mx-auto flex w-full max-w-2xl">
        {#each navItems as item (item.path)}
          <li class="flex-1">
            <a
              href="#{navPath(item.path)}"
              onclick={(event) => retryActiveSession(event, item.path)}
              aria-label={navLabel(item.path, item.label)}
              aria-current={isCurrentPage(item.path) ? 'page' : undefined}
              title={navLabel(item.path, item.label)}
              class="flex min-h-11 min-w-11 w-full items-center justify-center px-2 py-3 {isCurrentPage(
                item.path,
              )
                ? 'text-primary'
                : 'text-muted'} {item.path === '/workouts/start' &&
              activeSession.workoutId !== null
                ? 'text-sync-ok drop-shadow-[0_0_6px_currentColor]'
                : ''} {item.path === '/workouts/start' &&
              activeSession.status === 'loading'
                ? 'animate-pulse'
                : ''}"
            >
              <ActionIcon name={item.icon} size={22} />
            </a>
          </li>
        {/each}
      </ul>
    </nav>
  {/if}
</div>
