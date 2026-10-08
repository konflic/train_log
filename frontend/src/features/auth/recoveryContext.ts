const KEY = 'basefit.recovery-account';

/** Only a non-secret account ID, never a credential or authentication claim. */
export function rememberRecoveryAccount(accountId: string): void {
  try {
    sessionStorage.setItem(KEY, accountId);
    localStorage.setItem(KEY, accountId);
  } catch {
    // Disabled Web Storage removes offline identity hints, not IndexedDB data.
  }
}

export function forgetRecoveryAccount(): void {
  try {
    sessionStorage.removeItem(KEY);
    localStorage.removeItem(KEY);
  } catch {
    // The caller also clears its in-memory permission to recover.
  }
}

export function recoveryAccount(): string | null {
  try {
    const account = sessionStorage.getItem(KEY);
    // A confirmed account in another tab invalidates an older tab's hint.
    return account && account === localStorage.getItem(KEY) ? account : null;
  } catch {
    return null;
  }
}

export function isRecoveryContextEvent(event: StorageEvent): boolean {
  return event.key === KEY || event.key === null;
}
