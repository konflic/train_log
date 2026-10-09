<script lang="ts">
  import packageInfo from '../../package.json';
  import { updateCurrentUser } from '../api';
  import { session } from '../features/auth/session.svelte';
  import { describeFailure, mapFailureToForm } from '../lib/failures';
  import { resolveTheme, setPreferredTheme, type Theme } from '../lib/theme';
  import { formatUtcOffset } from '../lib/offsetTime';

  const HOUR_OFFSETS = Array.from(
    { length: 27 },
    (_, index) => (index - 12) * 60,
  );
  const initialTheme = resolveTheme().theme;
  let theme = $state<Theme>(initialTheme);
  let themeMessage = $state<string | null>(null);
  let displayName = $state(session.user?.display_name ?? '');
  let bodyweight = $state(
    session.user?.bodyweight_default_kg === null || session.user === null
      ? ''
      : String(session.user.bodyweight_default_kg),
  );
  let offset = $state(session.user?.utc_offset_minutes ?? 0);
  let profileBusy = $state(false);
  let profileError = $state<string | null>(null);
  let logoutBusy = $state(false);
  let logoutError = $state<string | null>(null);

  function wholePositiveOrNull(value: string): number | null | undefined {
    if (value === '') return null;
    if (!/^[1-9]\d*$/.test(value)) return undefined;
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) ? parsed : undefined;
  }

  function chooseTheme(next: Theme): void {
    theme = next;
    const outcome = setPreferredTheme(next);
    themeMessage = outcome.persisted
      ? null
      : 'The theme applies now but could not be saved on this device.';
  }

  async function saveProfile(): Promise<void> {
    if (profileBusy) return;
    const parsedBodyweight = wholePositiveOrNull(bodyweight);
    if (parsedBodyweight === undefined) {
      profileError = 'Bodyweight must be a whole positive kilogram value.';
      return;
    }
    profileBusy = true;
    profileError = null;
    try {
      const updated = await updateCurrentUser({
        display_name: displayName.trim() || null,
        bodyweight_default_kg: parsedBodyweight,
        utc_offset_minutes: offset,
      });
      session.user = updated;
    } catch (error) {
      profileError = mapFailureToForm(error).form ?? describeFailure(error);
    } finally {
      profileBusy = false;
    }
  }

  async function beginLogout(): Promise<void> {
    if (logoutBusy || session.user === null) return;
    logoutBusy = true;
    logoutError = null;
    try {
      await session.signOut();
    } catch (error) {
      logoutError = describeFailure(error);
    } finally {
      logoutBusy = false;
    }
  }
</script>

<svelte:head><title>Settings · BaseFit</title></svelte:head>
<h1 tabindex="-1">Settings</h1>
<section
  class="mt-6 rounded-lg border border-edge bg-surface p-4"
  aria-labelledby="appearance-heading"
>
  <h2 id="appearance-heading" class="text-lg font-semibold">Appearance</h2>
  <fieldset class="mt-3 flex gap-3">
    <legend class="sr-only">Theme</legend>
    <label
      ><input
        type="radio"
        name="theme"
        value="light"
        checked={theme === 'light'}
        onchange={() => chooseTheme('light')}
      /> Light</label
    >
    <label
      ><input
        type="radio"
        name="theme"
        value="dark"
        checked={theme === 'dark'}
        onchange={() => chooseTheme('dark')}
      /> Dark</label
    >
  </fieldset>
  {#if themeMessage}<p role="alert" class="mt-2 text-sm text-danger">
      {themeMessage}
    </p>{/if}
</section>
<section
  class="mt-4 rounded-lg border border-edge bg-surface p-4"
  aria-labelledby="profile-heading"
>
  <h2 id="profile-heading" class="text-lg font-semibold">Profile</h2>
  <form
    class="mt-3 flex flex-col gap-3"
    onsubmit={(event) => {
      event.preventDefault();
      void saveProfile();
    }}
  >
    <label class="text-sm font-medium"
      >Display name<input
        bind:value={displayName}
        maxlength="100"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
      /></label
    >
    <label class="text-sm font-medium"
      >Bodyweight (kg)<input
        bind:value={bodyweight}
        inputmode="numeric"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
      /></label
    >
    <label class="text-sm font-medium"
      >Calendar offset<select
        bind:value={offset}
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
      >
        {#if !HOUR_OFFSETS.includes(offset)}<option value={offset}
            >{formatUtcOffset(offset)} (current)</option
          >{/if}
        {#each HOUR_OFFSETS as value (value)}<option {value}
            >{formatUtcOffset(value)}</option
          >{/each}
      </select></label
    >
    {#if profileError}<p role="alert" class="text-sm text-danger">
        {profileError}
      </p>{/if}
    <button
      type="submit"
      disabled={profileBusy}
      class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
      >{profileBusy ? 'Saving…' : 'Save profile'}</button
    >
  </form>
</section>
<section
  class="mt-4 rounded-lg border border-edge bg-surface p-4"
  aria-labelledby="account-settings-heading"
>
  <h2 id="account-settings-heading" class="text-lg font-semibold">Account</h2>
  {#if logoutError}<p role="alert" class="mt-3 text-sm text-danger">
      {logoutError}
    </p>{/if}
  <button
    id="settings-logout-button"
    type="button"
    disabled={logoutBusy}
    class="mt-3 min-h-11 rounded-md border border-danger px-4 font-medium text-danger disabled:opacity-40"
    onclick={() => void beginLogout()}
    >{logoutBusy ? 'Logging out…' : 'Log out'}</button
  >
</section>
<p class="mt-8 text-sm text-muted">Version {packageInfo.version}</p>
