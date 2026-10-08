/**
 * Small authentication state module (Stage 10): no state-management
 * dependency, just Svelte 5 runes in a `.svelte.ts` module. The session is
 * initialized once from `GET /auth/me`; every response is guarded by request
 * identity (a generation counter) so a superseded request can never restore a
 * stale user or another user's data. No credential or token is ever persisted
 * by frontend code; the session cookie stays HttpOnly.
 */

import { ApiRequestError, type PublicUser, fetchCurrentUser } from '../../api';

export type SessionStatus = 'loading' | 'anonymous' | 'authenticated' | 'error';

export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.problem.status === 401;
}

export class SessionState {
  status = $state<SessionStatus>('loading');
  user = $state<PublicUser | null>(null);

  /** Identity guard: only the newest request may write state. */
  private generation = 0;

  /** Resolve the session once at startup; failures render a retry state. */
  async initialize(): Promise<void> {
    const generation = ++this.generation;
    this.status = 'loading';
    try {
      const user = await fetchCurrentUser();
      if (generation !== this.generation) {
        return;
      }
      this.user = user;
      this.status = 'authenticated';
    } catch (error) {
      if (generation !== this.generation) {
        return;
      }
      this.user = null;
      // Network/server failures are not a logged-out state.
      this.status = isUnauthorizedError(error) ? 'anonymous' : 'error';
    }
  }

  /**
   * Adopt the user returned by an explicit login. The caller performs the
   * API request and navigation; adopting bumps the generation so any older
   * in-flight read can no longer write state.
   */
  adoptUser(user: PublicUser): void {
    this.generation += 1;
    this.user = user;
    this.status = 'authenticated';
  }

  /** A 401 from a protected read invalidates the signed-in state. */
  noteUnauthorized(): void {
    this.generation += 1;
    this.user = null;
    this.status = 'anonymous';
  }
}

export const session = new SessionState();

/**
 * The requested route preserved in memory for the current page load only;
 * a successful login returns there.
 */
let intendedRoute: string | null = null;

export function rememberIntendedRoute(route: string): void {
  intendedRoute = route;
}

export function takeIntendedRoute(): string | null {
  const route = intendedRoute;
  intendedRoute = null;
  return route;
}

/** Register-to-login convenience: normalized email and success notice. */
let loginPrefillEmail: string | null = null;
let registrationNotice = false;

export function primeLoginAfterRegistration(email: string): void {
  loginPrefillEmail = email;
  registrationNotice = true;
}

export function takeLoginPrefillEmail(): string | null {
  const email = loginPrefillEmail;
  loginPrefillEmail = null;
  return email;
}

export function takeRegistrationNotice(): boolean {
  const noticed = registrationNotice;
  registrationNotice = false;
  return noticed;
}
