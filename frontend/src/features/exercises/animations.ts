/**
 * Animation manifest: maps a backend `animation_key` to its two bundled SVG
 * frames. Frames are local build assets resolved eagerly by Vite; no image is
 * ever fetched from a third-party origin at runtime. A missing frame leaves
 * the manifest entry incomplete, and `animationFrames` reports it as absent
 * (enforced by the manifest unit test and the backend consistency test).
 * Custom exercises have no manifest entry and their screens omit the media
 * section entirely.
 */

const frames = import.meta.glob('../../assets/exercises/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>;

export interface ExerciseAnimationFrames {
  start: string;
  finish: string;
}

function buildManifest(): Record<string, ExerciseAnimationFrames> {
  const manifest: Record<string, ExerciseAnimationFrames> = {};
  for (const [path, url] of Object.entries(frames)) {
    const file = path.slice(path.lastIndexOf('/') + 1).replace(/\.svg$/, '');
    const separator = file.lastIndexOf('-');
    if (separator < 0) continue;
    const key = file.slice(0, separator);
    const variant = file.slice(separator + 1);
    if (variant !== 'start' && variant !== 'finish') continue;
    const entry = (manifest[key] ??= { start: '', finish: '' });
    entry[variant] = url;
  }
  return manifest;
}

export const exerciseAnimations: Readonly<
  Record<string, ExerciseAnimationFrames>
> = buildManifest();

/** Both frames of one animation key, or `null` when unavailable. */
export function animationFrames(key: string): ExerciseAnimationFrames | null {
  const entry = exerciseAnimations[key];
  if (!entry || entry.start === '' || entry.finish === '') return null;
  return entry;
}
