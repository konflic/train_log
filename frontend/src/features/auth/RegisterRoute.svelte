<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { replace } from 'svelte-spa-router';
  import { registerUser } from '../../api';
  import { mapFailureToForm, type FormFailure } from '../../lib/failures';
  import { primeLoginAfterRegistration, session } from './session.svelte';
  import {
    normalizeEmailInput,
    validateAge,
    validateDisplayName,
    validateEmail,
    validateInitialWeight,
    validatePassword,
  } from './validation';

  const noErrors: FormFailure = { form: null, fields: {} };

  let email = $state('');
  let password = $state('');
  let displayName = $state('');
  let initialWeight = $state('');
  let sex = $state<'male' | 'female'>('male');
  let age = $state('');
  let submitting = $state(false);
  let registeredEmail = $state<string | null>(null);
  let errors = $state<FormFailure>(noErrors);
  let headingRef = $state<HTMLElement | undefined>();
  let alertRef = $state<HTMLElement | undefined>();

  onMount(() => {
    // Authenticated visits to auth routes lead to Home.
    if (session.status === 'authenticated') {
      void replace('/');
    }
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
    const displayNameError = validateDisplayName(displayName);
    if (displayNameError !== null) {
      fields.display_name = displayNameError;
    }
    const initialWeightError = validateInitialWeight(initialWeight);
    if (initialWeightError !== null) {
      fields.bodyweight_default_kg = initialWeightError;
    }
    const ageError = validateAge(age);
    if (ageError !== null) {
      fields.age = ageError;
    }
    errors = { form: null, fields };
    if (Object.keys(fields).length > 0) {
      await focusAfterFailure();
      return;
    }
    submitting = true;
    const normalizedEmail = normalizeEmailInput(email);
    const trimmedName = displayName.trim();
    try {
      // Registration never logs the user in; success moves to login.
      await registerUser({
        email: normalizedEmail,
        password,
        display_name: trimmedName === '' ? undefined : trimmedName,
        bodyweight_default_kg: Number(initialWeight),
        sex,
        age: Number(age),
      });
      password = '';
      registeredEmail = normalizedEmail;
    } catch (error) {
      errors = mapFailureToForm(error);
      await focusAfterFailure();
    } finally {
      submitting = false;
    }
  }

  async function continueToLogin(): Promise<void> {
    if (registeredEmail !== null) {
      primeLoginAfterRegistration(registeredEmail);
    }
    await replace('/login');
  }
</script>

<svelte:head>
  <title>Create account · BaseFit</title>
</svelte:head>

<section
  id="register-screen"
  class="w-full rounded-xl border border-edge bg-surface p-5 shadow-sm sm:p-6"
>
  <h1 id="register-heading" tabindex="-1" bind:this={headingRef}>
    Create account
  </h1>

  {#if registeredEmail !== null}
    <p
      id="register-notice"
      role="status"
      class="mt-3 rounded-md border border-edge bg-surface px-3 py-2 text-sm"
    >
      Account created for {registeredEmail}, registration does not sign you in
    </p>
    <button
      id="register-continue-login-button"
      type="button"
      class="mt-4 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
      onclick={() => void continueToLogin()}
    >
      Continue to log in
    </button>
  {:else}
    {#if errors.form !== null}
      <p
        id="register-form-error"
        role="alert"
        tabindex="-1"
        bind:this={alertRef}
        class="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
      >
        {errors.form}
      </p>
    {/if}

    <form
      id="register-form"
      class="mt-4 flex w-full flex-col gap-4"
      novalidate
      onsubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
    >
      <div>
        <label for="register-email" class="block text-sm font-medium"
          >Email</label
        >
        <input
          id="register-email"
          name="email"
          type="email"
          autocomplete="username"
          inputmode="email"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={email}
          aria-invalid={errors.fields.email !== undefined}
          aria-describedby={errors.fields.email !== undefined
            ? 'register-email-error'
            : undefined}
        />
        {#if errors.fields.email !== undefined}
          <p id="register-email-error" class="mt-1 text-sm text-danger">
            {errors.fields.email}
          </p>
        {/if}
      </div>

      <div>
        <label for="register-password" class="block text-sm font-medium"
          >Password</label
        >
        <input
          id="register-password"
          name="password"
          type="password"
          autocomplete="new-password"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={password}
          aria-invalid={errors.fields.password !== undefined}
          aria-describedby={errors.fields.password !== undefined
            ? 'register-password-error register-password-hint'
            : 'register-password-hint'}
        />
        <p id="register-password-hint" class="mt-1 text-xs text-muted">
          At least 8 characters
        </p>
        {#if errors.fields.password !== undefined}
          <p id="register-password-error" class="mt-1 text-sm text-danger">
            {errors.fields.password}
          </p>
        {/if}
      </div>

      <div>
        <label for="register-display-name" class="block text-sm font-medium">
          Display name (optional)
        </label>
        <input
          id="register-display-name"
          name="display_name"
          type="text"
          autocomplete="nickname"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={displayName}
          aria-invalid={errors.fields.display_name !== undefined}
          aria-describedby={errors.fields.display_name !== undefined
            ? 'register-display-name-error'
            : undefined}
        />
        {#if errors.fields.display_name !== undefined}
          <p id="register-display-name-error" class="mt-1 text-sm text-danger">
            {errors.fields.display_name}
          </p>
        {/if}
      </div>

      <div>
        <label for="register-initial-weight" class="block text-sm font-medium"
          >Initial weight (kg)</label
        >
        <input
          id="register-initial-weight"
          name="bodyweight_default_kg"
          type="number"
          min="1"
          step="1"
          inputmode="numeric"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={initialWeight}
          aria-invalid={errors.fields.bodyweight_default_kg !== undefined}
          aria-describedby={errors.fields.bodyweight_default_kg !== undefined
            ? 'register-initial-weight-error'
            : undefined}
        />
        {#if errors.fields.bodyweight_default_kg !== undefined}
          <p
            id="register-initial-weight-error"
            class="mt-1 text-sm text-danger"
          >
            {errors.fields.bodyweight_default_kg}
          </p>
        {/if}
      </div>

      <div>
        <label for="register-sex" class="block text-sm font-medium">Sex</label>
        <select
          id="register-sex"
          name="sex"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={sex}
          required
          aria-invalid={errors.fields.sex !== undefined}
          aria-describedby={errors.fields.sex !== undefined
            ? 'register-sex-error'
            : undefined}
        >
          <option value="male">Male</option>
          <option value="female">Female</option>
        </select>
        {#if errors.fields.sex !== undefined}
          <p id="register-sex-error" class="mt-1 text-sm text-danger">
            {errors.fields.sex}
          </p>
        {/if}
      </div>

      <div>
        <label for="register-age" class="block text-sm font-medium">Age</label>
        <input
          id="register-age"
          name="age"
          type="number"
          min="1"
          max="120"
          step="1"
          inputmode="numeric"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={age}
          aria-invalid={errors.fields.age !== undefined}
          aria-describedby={errors.fields.age !== undefined
            ? 'register-age-error'
            : undefined}
        />
        {#if errors.fields.age !== undefined}
          <p id="register-age-error" class="mt-1 text-sm text-danger">
            {errors.fields.age}
          </p>
        {/if}
      </div>

      <button
        id="register-submit-button"
        type="submit"
        disabled={submitting}
        class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-60"
      >
        {submitting ? 'Creating account…' : 'Create account'}
      </button>
    </form>

    <p class="mt-4 text-sm text-muted">
      Already registered?
      <a
        id="register-login-link"
        href="#/login"
        class="min-h-11 inline-flex items-center text-primary underline"
      >
        Log in
      </a>
    </p>
  {/if}
</section>
