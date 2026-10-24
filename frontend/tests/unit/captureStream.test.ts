import { describe, expect, it } from 'vitest';

import { parseSse, toStreamEvent } from '../../src/api/captureStream';

describe('parseSse', () => {
  it('splits whole frames and keeps the unfinished tail', () => {
    const { frames, rest } = parseSse(
      'event: prompt\ndata: {"a":1}\n\nevent: resolved\ndata: {"prompt_id":"p","event_id":"e"}\n\nevent: prom',
    );
    expect(frames.map((f) => f.event)).toEqual(['prompt', 'resolved']);
    expect(rest).toBe('event: prom');
  });

  it('drops keepalive comments and malformed data without stopping', () => {
    const { frames } = parseSse(
      ': keepalive\n\nevent: prompt\ndata: not json\n\nevent: prompt\ndata: {"ok":true}\n\n',
    );
    expect(frames).toEqual([{ event: 'prompt', data: { ok: true } }]);
  });

  it('copes with windows line endings and a frame split across reads', () => {
    const first = parseSse('event: prompt\r\ndata: {"x"');
    expect(first.frames).toHaveLength(0);
    const second = parseSse(first.rest + ':1}\r\n\r\n');
    expect(second.frames).toEqual([{ event: 'prompt', data: { x: 1 } }]);
  });

  it('turns frames into typed events and ignores unknown ones', () => {
    expect(toStreamEvent({ event: 'resolved', data: { prompt_id: 'p1', event_id: 'e1' } })).toEqual(
      {
        type: 'resolved',
        promptId: 'p1',
        eventId: 'e1',
      },
    );
    expect(toStreamEvent({ event: 'surprise', data: {} })).toBeNull();
  });
});
