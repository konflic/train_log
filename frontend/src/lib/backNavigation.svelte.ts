/**
 * Minimal in-app back-destination memo for routes that need a "Back" link
 * honoring where the user came from, with a deterministic fallback for
 * direct route visits. It records hash-route locations only (never draft or
 * synchronization state) and does not persist across page loads.
 */

let previous = $state.raw<string | null>(null);
let current = $state.raw<string | null>(null);

/** Record one router location change (path without querystring). */
export function noteLocation(location: string): void {
  if (location === current) return;
  previous = current;
  current = location;
}

/** The previous in-app location, or `fallback` on a direct visit. */
export function backDestination(fallback: string): string {
  return previous ?? fallback;
}
