import { afterEach, describe, expect, it, vi } from 'vitest';

import { streamAsk, type AgentStep } from '../../src/api/askStream';
import { ApiError } from '../../src/api/client';

const enc = new TextEncoder();

/** A response whose body arrives in the given pieces, the way a network delivers it. */
function streamed(chunks: string[], init: ResponseInit = { status: 200 }): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(body, init);
}

const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

afterEach(() => vi.unstubAllGlobals());

describe('streamAsk', () => {
  it('hands each step over as it arrives, then resolves with the result', async () => {
    const all =
      frame('step', { stage: 'start', title: 'Reading your question', ms: 1 }) +
      frame('step', { stage: 'plan', title: 'Planned 2 steps', ms: 40 }) +
      ': keepalive\n\n' +
      frame('result', { status: 'completed', answer: null });
    // cut in the middle of a frame, and in the middle of a word
    const cuts = [all.slice(0, 30), all.slice(30, 110), all.slice(110)];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed(cuts)));

    const seen: AgentStep[] = [];
    const result = await streamAsk({ text: 'why', onStep: (s) => seen.push(s) });

    expect(seen.map((s) => s.stage)).toEqual(['start', 'plan']);
    expect(seen[1]?.ms).toBe(40);
    expect(result.status).toBe('completed');
  });

  it('sends the question in the body and the token in a header, never in the address', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(streamed([frame('result', { status: 'completed' })]));
    vi.stubGlobal('fetch', fetchMock);
    await streamAsk({ text: 'secret question', clarification: 'food', onStep: () => {} });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/ask/stream');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toMatchObject({
      text: 'secret question',
      clarification: 'food',
    });
    expect((init.headers as Record<string, string>).Authorization).toMatch(/^Bearer /);
  });

  it('turns an error event into a typed, retryable error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(streamed([frame('error', { message: 'Try again.' })])),
    );
    await expect(streamAsk({ text: 'x', onStep: () => {} })).rejects.toMatchObject({
      code: 'AGENT_FAILED',
      retryable: true,
      message: 'Try again.',
    });
  });

  it('fails clearly when the stream ends without a result', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(streamed([frame('step', { stage: 'start', title: 't', ms: 0 })])),
    );
    await expect(streamAsk({ text: 'x', onStep: () => {} })).rejects.toBeInstanceOf(ApiError);
  });

  it('reads the API error of a refused request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: 'UNAUTHORIZED', message: 'No token.' }), {
          status: 401,
        }),
      ),
    );
    await expect(streamAsk({ text: 'x', onStep: () => {} })).rejects.toMatchObject({
      code: 'UNAUTHORIZED',
      status: 401,
    });
  });

  it('says the service is unreachable when the network fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')));
    await expect(streamAsk({ text: 'x', onStep: () => {} })).rejects.toMatchObject({
      code: 'UNREACHABLE',
    });
  });
});
