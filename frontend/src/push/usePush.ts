import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';

export type PushState =
  | 'unsupported' // this browser cannot do it
  | 'insecure' // needs https or http://localhost
  | 'denied' // the person said no in the browser
  | 'off'
  | 'on';

/** The key the browser needs, as bytes (it travels as url-safe base64). */
export function keyToBytes(key: string): Uint8Array<ArrayBuffer> {
  const padded = key + '='.repeat((4 - (key.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/** A short name for this device so the list of devices means something. */
export function deviceLabel(ua: string = navigator.userAgent): string {
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /Chrome\//.test(ua)
      ? 'Chrome'
      : /Firefox\//.test(ua)
        ? 'Firefox'
        : /Safari\//.test(ua)
          ? 'Safari'
          : 'Browser';
  const os = /Android/.test(ua)
    ? 'Android'
    : /iPhone|iPad/.test(ua)
      ? 'iPhone'
      : /Windows/.test(ua)
        ? 'Windows'
        : /Mac OS/.test(ua)
          ? 'Mac'
          : /Linux/.test(ua)
            ? 'Linux'
            : '';
  return os ? `${browser} on ${os}` : browser;
}

function supportState(): PushState | null {
  if (typeof window === 'undefined') return 'unsupported';
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window))
    return 'unsupported';
  if (!window.isSecureContext) return 'insecure';
  if (Notification.permission === 'denied') return 'denied';
  return null;
}

/** Turn notifications on or off for this device, and report where things stand. */
export function usePush() {
  const [state, setState] = useState<PushState>(() => supportState() ?? 'off');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (supportState()) return; // the starting state already says why
    let live = true;
    void navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => live && setState(sub ? 'on' : 'off'))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const enable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setState(permission === 'denied' ? 'denied' : 'off');
        return;
      }
      const status = await api.pushStatus();
      const reg = await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyToBytes(status.public_key),
        }));
      const json = sub.toJSON();
      await api.pushSubscribe({
        endpoint: sub.endpoint,
        keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' },
        label: deviceLabel(),
      });
      setState('on');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not turn notifications on here.');
    } finally {
      setBusy(false);
    }
  }, []);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await api.pushUnsubscribe(sub.endpoint);
        await sub.unsubscribe();
      }
      setState('off');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not turn notifications off.');
    } finally {
      setBusy(false);
    }
  }, []);

  return { state, busy, error, enable, disable };
}
