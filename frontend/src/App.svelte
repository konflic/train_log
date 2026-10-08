<script lang="ts">
  import Router, { replace, router } from 'svelte-spa-router';
  import LoginRoute from './features/auth/LoginRoute.svelte';
  import RegisterRoute from './features/auth/RegisterRoute.svelte';
  import {
    rememberIntendedRoute,
    session,
  } from './features/auth/session.svelte';
  import CatalogRoute from './features/catalog/CatalogRoute.svelte';
  import HomeRoute from './features/home/HomeRoute.svelte';
  import { initializeTheme } from './lib/theme';
  import HistoryRoute from './routes/HistoryRoute.svelte';
  import NotFoundRoute from './routes/NotFoundRoute.svelte';
  import SettingsRoute from './routes/SettingsRoute.svelte';

  // Hash route table: production serving needs no SPA rewrite rule. Feature
  // routes render clearly labeled placeholders until their owning stage.
  const routes = {
    '/': HomeRoute,
    '/catalog': CatalogRoute,
    '/history': HistoryRoute,
    '/settings': SettingsRoute,
    '/login': LoginRoute,
    '/register': RegisterRoute,
    '*': NotFoundRoute,
  };

  // Bottom navigation targets (text labels, at least 44 CSS pixels).
  const navItems: ReadonlyArray<{ path: string; label: string }> = [
    { path: '/', label: 'Home' },
    { path: '/catalog', label: 'Catalog' },
    { path: '/history', label: 'History' },
    { path: '/settings', label: 'Settings' },
  ];

  const authPaths = new Set(['/login', '/register']);

  // The inline bootstrap in index.html already applied the theme before
  // first paint; applying it again keeps direct mounts (tests, HMR)
  // consistent with the shared theme module.
  initializeTheme();

  // Resolve the session once at startup from GET /auth/me.
  void session.initialize();

  function isCurrentPage(path: string): boolean {
    const current = router.location;
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
      rememberIntendedRoute(querystring ? `${path}?${querystring}` : path);
      void replace('/login');
    }
  });
</script>

<div class="flex min-h-dvh flex-col">
  <main
    class="mx-auto w-full max-w-2xl flex-1 px-4 pt-4 {showChrome
      ? 'pb-28'
      : 'pb-8'}"
  >
    {#if session.status === 'loading'}
      <p role="status">Checking your session…</p>
    {:else if session.status === 'error'}
      <h1 tabindex="-1">Cannot reach the server</h1>
      <p class="mt-2 text-muted">
        Your session could not be checked, so you were not signed out. Retry
        when the connection is back.
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
      class="fixed inset-x-0 bottom-0 border-t border-edge bg-surface"
    >
      <ul class="mx-auto flex w-full max-w-2xl">
        {#each navItems as item (item.path)}
          <li class="flex-1">
            <a
              href="#{item.path}"
              aria-current={isCurrentPage(item.path) ? 'page' : undefined}
              class="flex min-h-11 w-full items-center justify-center px-2 py-3 text-sm font-medium {isCurrentPage(
                item.path,
              )
                ? 'text-primary'
                : 'text-muted'}"
            >
              {item.label}
            </a>
          </li>
        {/each}
      </ul>
    </nav>
  {/if}
</div>
