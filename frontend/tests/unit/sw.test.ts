import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it, vi } from 'vitest';

type Handler = (event: unknown) => void;

/** Run the real public/sw.js against a fake service-worker scope. */
function load(
  opts: { windows?: { focused: boolean; visible: boolean }[]; fetchOk?: boolean } = {},
) {
  const handlers = new Map<string, Handler>();
  const shown: { title: string; options: Record<string, unknown> }[] = [];
  const open: { tag: string; close: () => void; closed: boolean }[] = [];
  const posted: unknown[] = [];
  const navigated: string[] = [];
  const opened: string[] = [];
  const windows = (opts.windows ?? []).map((w) => ({
    focused: w.focused,
    visibilityState: w.visible ? 'visible' : 'hidden',
    postMessage: (m: unknown) => posted.push(m),
    focus: async () => undefined,
    navigate: async (u: string) => void navigated.push(u),
  }));
  const fetchMock = vi.fn(async () => ({ ok: opts.fetchOk ?? true }));
  const scope = {
    addEventListener: (type: string, fn: Handler) => handlers.set(type, fn),
    skipWaiting: () => undefined,
    clients: {
      claim: async () => undefined,
      matchAll: async () => windows,
      openWindow: async (u: string) => void opened.push(u),
    },
    registration: {
      showNotification: async (title: string, options: Record<string, unknown>) => {
        shown.push({ title, options });
        const n = {
          tag: String(options.tag),
          closed: false,
          close() {
            n.closed = true;
          },
        };
        open.push(n);
      },
      getNotifications: async ({ tag }: { tag: string }) =>
        open.filter((n) => n.tag === tag && !n.closed),
    },
  };
  new Function('self', 'fetch', readFileSync(join(__dirname, '../../public/sw.js'), 'utf8'))(
    scope,
    fetchMock,
  );
  const run = async (type: string, event: Record<string, unknown>) => {
    const waits: Promise<unknown>[] = [];
    handlers.get(type)?.({ ...event, waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
  };
  return { run, shown, open, posted, navigated, opened, fetchMock };
}

const prompt = {
  type: 'prompt',
  prompt_id: 'prm_1',
  event_id: 'pev_1',
  credit: false,
  title: '1 payment to tag',
  body: 'Open FinCo to say what it was.',
  tag: 'prm_1',
  token: 'tok-abc-123456',
  actions: [
    { action: 'label:food', title: 'Dining' },
    { action: 'label:travel', title: 'Travel' },
  ],
  ranks: { 'label:food': 1, 'label:travel': 2 },
};
const push = (data: unknown) => ({ data: { json: () => data } });

describe('the service worker', () => {
  it('shows the prompt as a notification with its buttons when no page is in front', async () => {
    const sw = load();
    await sw.run('push', push(prompt));
    expect(sw.shown).toHaveLength(1);
    const { title, options } = sw.shown[0]!;
    expect(title).toBe('1 payment to tag');
    expect(options.tag).toBe('prm_1');
    expect((options.actions as { action: string }[]).map((a) => a.action)).toEqual([
      'label:food',
      'label:travel',
    ]);
    expect(options.requireInteraction).toBe(true);
  });

  it('leaves the asking to the open page when one is focused', async () => {
    const sw = load({ windows: [{ focused: true, visible: true }] });
    await sw.run('push', push(prompt));
    expect(sw.shown).toHaveLength(0);
    expect(sw.posted).toEqual([{ type: 'prompt', prompt_id: 'prm_1' }]);
  });

  it('still notifies when a page is open but in the background', async () => {
    const sw = load({ windows: [{ focused: false, visible: false }] });
    await sw.run('push', push(prompt));
    expect(sw.shown).toHaveLength(1);
  });

  it('a button press answers with its single-use token and the right rank, without opening the app', async () => {
    const sw = load();
    await sw.run('push', push(prompt));
    const notification = { data: sw.shown[0]!.options.data, close: vi.fn() };
    await sw.run('notificationclick', { notification, action: 'label:travel' });
    expect(sw.fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = sw.fetchMock.mock.calls[0] as unknown as [string, { body: string }];
    expect(url).toBe('/api/capture/push/action');
    expect(JSON.parse(init.body)).toEqual({
      prompt_id: 'prm_1',
      token: 'tok-abc-123456',
      label: 'travel',
      rank: 2,
      credit: false,
    });
    expect(notification.close).toHaveBeenCalled();
    expect(sw.opened).toEqual([]);
  });

  it('tapping the body opens the app on that payment', async () => {
    const sw = load();
    await sw.run('push', push(prompt));
    await sw.run('notificationclick', {
      notification: { data: sw.shown[0]!.options.data, close: vi.fn() },
      action: '',
    });
    expect(sw.fetchMock).not.toHaveBeenCalled();
    expect(sw.opened).toEqual(['/capture?prompt=prm_1']);
  });

  it('opens the app instead when the button cannot be answered', async () => {
    const sw = load({ fetchOk: false });
    await sw.run('push', push(prompt));
    await sw.run('notificationclick', {
      notification: { data: sw.shown[0]!.options.data, close: vi.fn() },
      action: 'label:food',
    });
    expect(sw.opened).toEqual(['/capture?prompt=prm_1']);
  });

  it('uses an open window rather than a new one', async () => {
    const sw = load({ windows: [{ focused: false, visible: false }] });
    await sw.run('push', push(prompt));
    await sw.run('notificationclick', {
      notification: { data: sw.shown[0]!.options.data, close: vi.fn() },
      action: '',
    });
    expect(sw.navigated).toEqual(['/capture?prompt=prm_1']);
    expect(sw.opened).toEqual([]);
  });

  it('closes its notification when another device answered', async () => {
    const sw = load();
    await sw.run('push', push(prompt));
    expect(sw.open.filter((n) => !n.closed)).toHaveLength(1);
    await sw.run('push', push({ type: 'close', prompt_id: 'prm_1', tag: 'prm_1' }));
    expect(sw.open.filter((n) => n.tag === 'prm_1' && !n.closed)).toHaveLength(0);
  });

  it('ignores a message it does not understand', async () => {
    const sw = load();
    await sw.run('push', {
      data: {
        json: () => {
          throw new Error('bad');
        },
      },
    });
    await sw.run('push', push({ type: 'surprise' }));
    expect(sw.shown).toHaveLength(0);
  });
});
