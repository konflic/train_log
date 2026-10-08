<script lang="ts">
  import type { Component } from 'svelte';
  import ActionIcon from './components/ActionIcon.svelte';
  import { isRecoveryContextEvent } from './features/auth/recoveryContext';
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
  import WorkoutRoute from './features/workout/WorkoutRoute.svelte';
  import OfflineRecovery from './features/workout/OfflineRecovery.svelte';

  let {
    draftHarness: DraftHarness,
  }: { draftHarness?: Component<{ accountId: string; localOnly: boolean }> } =
    $props();
  let localRecoverySelected = $state(false);

  // Hash route table: production serving needs no SPA rewrite rule. Feature
  // routes render clearly labeled placeholders until their owning stage.
  const routes = {
    '/': HomeRoute,
    '/catalog': CatalogRoute,
    '/history': HistoryRoute,
    '/settings': SettingsRoute,
    '/workouts/:id': WorkoutRoute,
    '/login': LoginRoute,
    '/register': RegisterRoute,
    '*': NotFoundRoute,
  };

  // Bottom navigation stays icon-only while retaining named, 44-pixel targets.
  const navItems: ReadonlyArray<{
    path: string;
    label: string;
    icon: 'home' | 'catalog' | 'history' | 'settings';
  }> = [
    { path: '/', label: 'Home', icon: 'home' },
    { path: '/catalog', label: 'Catalog', icon: 'catalog' },
    { path: '/history', label: 'History', icon: 'history' },
    { path: '/settings', label: 'Settings', icon: 'settings' },
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
</script>

<svelte:window
  onstorage={(event) => {
    if (isRecoveryContextEvent(event)) session.refreshRecoveryContext();
  }}
/>

<div class="flex min-h-dvh flex-col">
  <main
    class="mx-auto w-full max-w-2xl flex-1 px-4 pt-4 {showChrome
      ? 'pb-4'
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
      {#if session.recoveryAccountId !== null}
        <p class="mt-4 text-muted">
          Local drafts for the previously confirmed account are available on
          this device. This does not sign you in.
        </p>
        <button
          type="button"
          class="mt-4 min-h-11 rounded-md border border-edge px-4"
          onclick={() => {
            localRecoverySelected = true;
          }}
        >
          Recover local drafts only
        </button>
        {#if localRecoverySelected && DraftHarness}
          {#key session.recoveryAccountId}
            <DraftHarness
              accountId={session.recoveryAccountId}
              localOnly={true}
            />
          {/key}
        {:else if localRecoverySelected}
          {#key session.recoveryAccountId}
            <OfflineRecovery accountId={session.recoveryAccountId} />
          {/key}
        {/if}
      {/if}
    {:else if routerReady}
      {#if DraftHarness && session.user !== null}
        {#key session.user.id}
          <DraftHarness accountId={session.user.id} localOnly={false} />
        {/key}
      {:else}
        <Router {routes} />
      {/if}
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
              href="#{item.path}"
              aria-label={item.label}
              aria-current={isCurrentPage(item.path) ? 'page' : undefined}
              title={item.label}
              class="flex min-h-11 min-w-11 w-full items-center justify-center px-2 py-3 {isCurrentPage(
                item.path,
              )
                ? 'text-primary'
                : 'text-muted'}"
            >
              <ActionIcon name={item.icon} size={22} />
            </a>
          </li>
        {/each}
      </ul>
    </nav>
  {/if}
</div>
