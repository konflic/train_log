// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { OpenDBCallbacks } from 'idb';

const { openMock } = vi.hoisted(() => ({ openMock: vi.fn() }));
vi.mock('idb', () => ({ openDB: openMock }));
import { closeDraftStorage, openDraftStorage } from './db';

afterEach(async () => {
  await closeDraftStorage();
  openMock.mockReset();
});

describe('draft database lifecycle', () => {
  it('retries an open failure and releases a cached connection on close', async () => {
    const close = vi.fn();
    openMock
      .mockRejectedValueOnce(new Error('storage disabled'))
      .mockResolvedValue({ close });
    await expect(openDraftStorage()).rejects.toThrow('storage disabled');
    await openDraftStorage();
    await closeDraftStorage();
    expect(close).toHaveBeenCalledOnce();
    await openDraftStorage();
    expect(openMock).toHaveBeenCalledTimes(3);
  });

  it('rejects a blocked upgrade visibly and closes its late connection', async () => {
    let callbacks!: OpenDBCallbacks<unknown>;
    let finish!: (value: { close: () => void }) => void;
    openMock.mockImplementationOnce((_name, _version, options) => {
      callbacks = options;
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    const blocked = openDraftStorage();
    callbacks.blocked!(0, 1, {} as IDBVersionChangeEvent);
    await expect(blocked).rejects.toThrow('blocked');
    const lateClose = vi.fn();
    finish({ close: lateClose });
    await Promise.resolve();
    expect(lateClose).toHaveBeenCalledOnce();
    openMock.mockResolvedValueOnce({ close: vi.fn() });
    await openDraftStorage();
    expect(openMock).toHaveBeenCalledTimes(2);
  });
});
