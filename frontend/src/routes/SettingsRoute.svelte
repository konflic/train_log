<script lang="ts">
  import packageInfo from '../../package.json';
  import { describeFailure } from '../lib/failures';
  import { session } from '../features/auth/session.svelte';

  let loggingOut = $state(false);
  let logoutError = $state<string | null>(null);

  async function signOut(): Promise<void> {
    if (loggingOut) return;
    loggingOut = true;
    logoutError = null;
    try {
      await session.signOut();
    } catch (error) {
      // Keep the authenticated UI available so a failed revocation can be retried.
      logoutError = describeFailure(error);
    } finally {
      loggingOut = false;
    }
  }
</script>

<h1 tabindex="-1">Settings</h1>
<p class="mt-2 text-muted">More preferences will arrive in a later update.</p>

<section class="mt-6" aria-labelledby="account-settings-heading">
  <h2 id="account-settings-heading" class="text-lg font-semibold">Account</h2>
  {#if logoutError !== null}
    <p
      role="alert"
      class="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
    >
      {logoutError}
    </p>
  {/if}
  <button
    type="button"
    disabled={loggingOut}
    class="mt-3 min-h-11 rounded-md border border-danger px-4 font-medium text-danger disabled:opacity-60"
    onclick={() => void signOut()}
  >
    {loggingOut ? 'Logging out…' : 'Log out'}
  </button>
</section>

<p class="mt-8 text-sm text-muted">Version {packageInfo.version}</p>
