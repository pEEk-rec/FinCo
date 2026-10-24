/*
 * FinCo service worker: shows payment prompts as notifications on this device and lets their
 * buttons answer the payment without opening the app.
 *
 * Plain JavaScript on purpose: it runs outside the app and cannot import anything. It never reads
 * the app's login; a notification button carries a single-use token that the backend checks.
 * tests/unit/sw.test.ts runs this exact file against a fake worker scope.
 */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

async function visibleWindow() {
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  return windows.find((c) => c.visibilityState === 'visible' && c.focused) || null;
}

async function closeByTag(tag) {
  const open = await self.registration.getNotifications({ tag });
  open.forEach((n) => n.close());
  if (open.length === 0 && !(await visibleWindow())) {
    // Browsers expect every push to show something; show it and take it straight back.
    await self.registration.showNotification('Payment tagged', { tag, silent: true });
    const shown = await self.registration.getNotifications({ tag });
    shown.forEach((n) => n.close());
  }
}

async function onPush(event) {
  let data;
  try {
    data = event.data.json();
  } catch {
    return;
  }
  if (data.type === 'close') return closeByTag(data.tag);
  if (data.type !== 'prompt') return;
  const focused = await visibleWindow();
  if (focused) {
    // A FinCo page is open and in front: its in-app prompt does the asking.
    focused.postMessage({ type: 'prompt', prompt_id: data.prompt_id });
    return;
  }
  await self.registration.showNotification(data.title, {
    body: data.body,
    tag: data.tag,
    requireInteraction: true,
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    data: {
      prompt_id: data.prompt_id,
      token: data.token,
      credit: data.credit,
      ranks: data.ranks,
      url: '/capture?prompt=' + encodeURIComponent(data.prompt_id),
    },
    actions: (data.actions || []).map((a) => ({ action: a.action, title: a.title })),
  });
}

self.addEventListener('push', (event) => event.waitUntil(onPush(event)));

async function openApp(url) {
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  if (windows.length > 0) {
    const w = windows[0];
    await w.focus();
    if (w.navigate) await w.navigate(url);
    return;
  }
  await self.clients.openWindow(url);
}

async function onClick(event) {
  const n = event.notification;
  const d = n.data || {};
  n.close();
  if (event.action && event.action.indexOf('label:') === 0) {
    try {
      const res = await fetch('/api/capture/push/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt_id: d.prompt_id,
          token: d.token,
          label: event.action.slice('label:'.length),
          rank: (d.ranks || {})[event.action] || 0,
          credit: !!d.credit,
        }),
      });
      if (res.ok) return;
    } catch {
      // offline or refused: fall through and open the app on this payment instead
    }
  }
  await openApp(d.url || '/capture');
}

self.addEventListener('notificationclick', (event) => event.waitUntil(onClick(event)));
