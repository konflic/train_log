import { render } from '@testing-library/svelte';
import { expect, it } from 'vitest';

import App from './App.svelte';

it('renders the application shell', () => {
  const { getByRole } = render(App);
  expect(getByRole('heading', { level: 1, name: 'BaseFit' })).toBeDefined();
});
