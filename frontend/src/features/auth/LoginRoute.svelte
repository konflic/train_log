<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import { replace } from 'svelte-spa-router';
  import {
    isAbortError,
    mapFailureToForm,
    type FormFailure,
  } from '../../lib/failures';
  import {
    session,
    takeIntendedRoute,
    takeLoginPrefillEmail,
    takeRegistrationNotice,
  } from './session.svelte';
  import {
    normalizeEmailInput,
    validateEmail,
    validatePassword,
  } from './validation';

  const noErrors: FormFailure = { form: null, fields: {} };

  let email = $state(takeLoginPrefillEmail() ?? '');
  let password = $state('');
  let submitting = $state(false);
  let errors = $state<FormFailure>(noErrors);
  let notice = $state<string | null>(
    takeRegistrationNotice() ? 'Account created. Log in to continue.' : null,
  );
  let headingRef = $state<HTMLElement | undefined>();
  let alertRef = $state<HTMLElement | undefined>();
  let controller: AbortController | null = null;

  onMount(() => {
    // Authenticated visits to auth routes lead to Home.
    if (session.status === 'authenticated') {
      void replace('/');
    }
  });

  onDestroy(() => {
    controller?.abort();
    session.cancelPendingAuthentication();
  });

  async function focusAfterFailure(): Promise<void> {
    await tick();
    (alertRef ?? headingRef)?.focus();
  }

  async function handleSubmit(): Promise<void> {
    if (submitting) {
      return;
    }
    const fields: Record<string, string> = {};
    const emailError = validateEmail(email);
    if (emailError !== null) {
      fields.email = emailError;
    }
    const passwordError = validatePassword(password);
    if (passwordError !== null) {
      fields.password = passwordError;
    }
    errors = { form: null, fields };
    if (Object.keys(fields).length > 0) {
      await focusAfterFailure();
      return;
    }
    submitting = true;
    controller = new AbortController();
    try {
      // No credential or token is stored in frontend persistence; the server
      // sets the HttpOnly cookie. Only the returned public user becomes the
      // current session, guarded by the session generation counter.
      const adopted = await session.authenticate(
        { email: normalizeEmailInput(email), password },
        controller.signal,
      );
      if (!adopted) {
        return;
      }
      password = '';
      await replace(takeIntendedRoute() ?? '/');
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
      errors = mapFailureToForm(error);
      await focusAfterFailure();
    } finally {
      controller = null;
      submitting = false;
    }
  }
</script>

<svelte:head>
  <title>Log in · BaseFit</title>
</svelte:head>

<h1 tabindex="-1" bind:this={headingRef}>Log in</h1>

{#if notice !== null}
  <p
    role="status"
    class="mt-3 rounded-md border border-edge bg-surface px-3 py-2 text-sm"
  >
    {notice}
  </p>
{/if}

{#if errors.form !== null}
  <p
    role="alert"
    tabindex="-1"
    bind:this={alertRef}
    class="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
  >
    {errors.form}
  </p>
{/if}

<form
  class="mt-4 flex flex-col gap-4"
  novalidate
  onsubmit={(event) => {
    event.preventDefault();
    void handleSubmit();
  }}
>
  <div>
    <label for="login-email" class="block text-sm font-medium">Email</label>
    <input
      id="login-email"
      name="email"
      type="email"
      autocomplete="username"
      inputmode="email"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
      bind:value={email}
      aria-invalid={errors.fields.email !== undefined}
      aria-describedby={errors.fields.email !== undefined
        ? 'login-email-error'
        : undefined}
    />
    {#if errors.fields.email !== undefined}
      <p id="login-email-error" class="mt-1 text-sm text-danger">
        {errors.fields.email}
      </p>
    {/if}
  </div>

  <div>
    <label for="login-password" class="block text-sm font-medium"
      >Password</label
    >
    <input
      id="login-password"
      name="password"
      type="password"
      autocomplete="current-password"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
      bind:value={password}
      aria-invalid={errors.fields.password !== undefined}
      aria-describedby={errors.fields.password !== undefined
        ? 'login-password-error'
        : undefined}
    />
    {#if errors.fields.password !== undefined}
      <p id="login-password-error" class="mt-1 text-sm text-danger">
        {errors.fields.password}
      </p>
    {/if}
  </div>

  <button
    type="submit"
    disabled={submitting}
    class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-60"
  >
    {submitting ? 'Logging in…' : 'Log in'}
  </button>
</form>

<p class="mt-4 text-sm text-muted">
  No account yet?
  <a
    href="#/register"
    class="min-h-11 inline-flex items-center text-primary underline"
  >
    Create one
  </a>
</p>
