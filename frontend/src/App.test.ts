import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import App from './App.svelte';

function navigateTo(hash: string): void {
  window.location.hash = hash;
}

beforeEach(() => {
  window.location.hash = '';
});

afterEach(() => {
  cleanup();
  window.location.hash = '';
});

describe('application shell', () => {
  it('renders the bottom navigation with text-label anchors', () => {
    render(App);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    const links = nav.querySelectorAll('a');
    expect(Array.from(links).map((link) => link.textContent?.trim())).toEqual([
      'Home',
      'Catalog',
      'History',
      'Settings',
    ]);
    // Keyboard-visible navigation: real anchors with hash targets.
    for (const link of links) {
      expect(link.getAttribute('href')).toMatch(/^#\//);
    }
    expect(nav.querySelector('a[href="#/catalog"]')).not.toBeNull();
  });

  it('renders Home by default and marks it as the current page', async () => {
    render(App);
    expect(await screen.findByRole('heading', { level: 1, name: 'Home' })).toBeDefined();
    const current = screen.getByRole('link', { name: 'Home' });
    expect(current.getAttribute('aria-current')).toBe('page');
    expect(
      screen
        .getByRole('link', { name: 'Catalog' })
        .hasAttribute('aria-current'),
    ).toBe(false);
  });

  it('routes to the catalog and moves the current-page marker', async () => {
    render(App);
    navigateTo('#/catalog');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Catalog' }),
      ).toBeDefined(),
    );
    expect(
      screen
        .getByRole('link', { name: 'Catalog' })
        .getAttribute('aria-current'),
    ).toBe('page');
    expect(
      screen.getByRole('link', { name: 'Home' }).hasAttribute('aria-current'),
    ).toBe(false);
  });

  it('routes to history and settings placeholders', async () => {
    render(App);
    navigateTo('#/history');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'History' }),
      ).toBeDefined(),
    );
    navigateTo('#/settings');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Settings' }),
      ).toBeDefined(),
    );
  });

  it('renders the not-found route for unknown hashes', async () => {
    render(App);
    navigateTo('#/definitely-not-a-route');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Page not found' }),
      ).toBeDefined(),
    );
    // No nav item claims to be current on the not-found route.
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(nav.querySelector('[aria-current="page"]')).toBeNull();
  });

  it('applies a theme class to the document root on mount', () => {
    localStorage.clear();
    render(App);
    const classes = document.documentElement.classList;
    expect(classes.contains('light') || classes.contains('dark')).toBe(true);
    expect(classes.contains('light') && classes.contains('dark')).toBe(false);
  });
});
