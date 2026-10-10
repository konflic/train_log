import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { animationFrames, exerciseAnimations } from './animations';

const ASSETS_DIR = resolve(process.cwd(), 'src/assets/exercises');

/** The seeded default catalog ids (backend migrations 0002/0006/0007). */
const DEFAULT_IDS = [
  'bench-press',
  'overhead-press',
  'barbell-row',
  'deadlift',
  'back-squat',
  'lat-pulldown',
  'leg-press',
  'pull-up',
  'push-up',
  'dip',
  'dumbbell-curl',
  'dumbbell-lateral-raise',
  'crunch',
  'sit-up',
  'hanging-leg-raise',
  'lying-leg-raise',
  'russian-twist',
  'ab-wheel-rollout',
  'back-extension',
  'dumbbell-bench-press',
  'romanian-deadlift',
  'lunge',
  'calf-raise',
  'hip-thrust',
  'triceps-pushdown',
  'face-pull',
  'front-squat',
  'goblet-squat',
  'sumo-deadlift',
  'good-morning',
  'incline-bench-press',
  'barbell-curl',
  'lying-triceps-extension',
  'dumbbell-overhead-press',
  'incline-dumbbell-bench-press',
  'one-arm-dumbbell-row',
  'hammer-curl',
  'dumbbell-romanian-deadlift',
  'kettlebell-swing',
  'chin-up',
  'bodyweight-squat',
  'close-grip-push-up',
];

describe('animation manifest', () => {
  it('has both bundled frames for every default exercise', () => {
    for (const key of DEFAULT_IDS) {
      const frames = animationFrames(key);
      expect(frames, key).not.toBeNull();
      expect(frames!.start).not.toBe('');
      expect(frames!.finish).not.toBe('');
      expect(frames!.start).not.toBe(frames!.finish);
    }
  });

  it('covers every bundled frame pair without orphans', () => {
    const files = readdirSync(ASSETS_DIR).filter((name) =>
      name.endsWith('.svg'),
    );
    const keys = new Set<string>();
    for (const file of files) {
      const match = /^(.+)-(start|finish)\.svg$/.exec(file);
      expect(match, file).not.toBeNull();
      keys.add(match![1]);
    }
    expect([...keys].sort()).toEqual([...DEFAULT_IDS].sort());
    expect(Object.keys(exerciseAnimations).sort()).toEqual(
      [...DEFAULT_IDS].sort(),
    );
  });

  it('reports custom or unknown keys as absent', () => {
    expect(animationFrames('some-custom-uuid')).toBeNull();
    expect(animationFrames('')).toBeNull();
  });
});
