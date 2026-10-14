import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const API = 'http://127.0.0.1:8765/api';
export const TOKEN = 'e2e-token';
export const authHeaders = { Authorization: `Bearer ${TOKEN}` };

/** Put the session token where the app looks for it, before any page script runs. */
export async function signIn(page: Page): Promise<void> {
  await page.addInitScript((token) => window.localStorage.setItem('finco.token', token), TOKEN);
}

export async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`${API}${path}`, { headers: authHeaders });
  expect(response.ok(), `${path} -> ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}
