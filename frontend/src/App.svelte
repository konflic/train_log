<script lang="ts">
  import Router, { router } from 'svelte-spa-router';
  import { initializeTheme } from './lib/theme';
  import CatalogRoute from './routes/CatalogRoute.svelte';
  import HistoryRoute from './routes/HistoryRoute.svelte';
  import HomeRoute from './routes/HomeRoute.svelte';
  import NotFoundRoute from './routes/NotFoundRoute.svelte';
  import SettingsRoute from './routes/SettingsRoute.svelte';

  // Hash route table: production serving needs no SPA rewrite rule. Feature
  // routes render clearly labeled placeholders until their owning stage.
  const routes = {
    '/': HomeRoute,
    '/catalog': CatalogRoute,
    '/history': HistoryRoute,
    '/settings': SettingsRoute,
    '*': NotFoundRoute,
  };

  // Bottom navigation targets (text labels, at least 44 CSS pixels).
  const navItems: ReadonlyArray<{ path: string; label: string }> = [
    { path: '/', label: 'Home' },
    { path: '/catalog', label: 'Catalog' },
    { path: '/history', label: 'History' },
    { path: '/settings', label: 'Settings' },
  ];

  // The inline bootstrap in index.html already applied the theme before
  // first paint; applying it again keeps direct mounts (tests, HMR)
  // consistent with the shared theme module.
  initializeTheme();

  function isCurrentPage(path: string): boolean {
    const current = router.location;
    return path === '/'
      ? current === '/'
      : current === path || current.startsWith(`${path}/`);
  }
</script>

<div class="flex min-h-dvh flex-col">
  <main class="mx-auto w-full max-w-2xl flex-1 px-4 pb-28 pt-4">
    <Router {routes} />
  </main>
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
</div>
