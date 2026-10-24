import { getToken, type PromptView } from './client';

/** One server-sent frame. `data` is the parsed JSON payload. */
export interface Frame {
  event: string;
  data: unknown;
}

/**
 * Split a buffer of server-sent events into whole frames and the unfinished remainder.
 * Comment lines (the keepalive) are dropped. Kept free of the network so it can be tested.
 */
export function parseSse(buffer: string): { frames: Frame[]; rest: string } {
  const frames: Frame[] = [];
  const parts = buffer.replace(/\r\n/g, '\n').split('\n\n');
  const rest = parts.pop() ?? '';
  for (const part of parts) {
    let event = 'message';
    const data: string[] = [];
    for (const line of part.split('\n')) {
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (data.length === 0) continue;
    try {
      frames.push({ event, data: JSON.parse(data.join('\n')) });
    } catch {
      // a malformed frame is skipped rather than stopping the stream
    }
  }
  return { frames, rest };
}

export interface AutoTagged {
  prompt_id: string;
  reason: string;
  name: string;
  event: PromptView['event'];
}

export type StreamEvent =
  | { type: 'prompt'; prompt: PromptView }
  | { type: 'resolved'; promptId: string; eventId: string }
  | { type: 'auto_tagged'; chip: AutoTagged };

export function toStreamEvent(frame: Frame): StreamEvent | null {
  const d = frame.data as Record<string, unknown>;
  switch (frame.event) {
    case 'prompt':
      return { type: 'prompt', prompt: d as unknown as PromptView };
    case 'resolved':
      return { type: 'resolved', promptId: String(d.prompt_id), eventId: String(d.event_id) };
    case 'auto_tagged':
      return { type: 'auto_tagged', chip: d as unknown as AutoTagged };
    default:
      return null;
  }
}

/**
 * Open the prompt stream and keep it open: it reconnects with a growing pause when the
 * connection drops, and a reconnect simply re-announces what is still waiting.
 * Returns a function that closes it.
 */
export function openCaptureStream(
  onEvent: (e: StreamEvent) => void,
  onState: (connected: boolean) => void,
): () => void {
  const controller = new AbortController();
  let delay = 1000;

  const run = async () => {
    while (!controller.signal.aborted) {
      try {
        const response = await fetch('/api/capture/stream', {
          headers: { Authorization: `Bearer ${getToken() ?? ''}` },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(String(response.status));
        onState(true);
        delay = 1000;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { frames, rest } = parseSse(buffer);
          buffer = rest;
          for (const frame of frames) {
            const event = toStreamEvent(frame);
            if (event) onEvent(event);
          }
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      onState(false);
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, 15000);
    }
  };
  void run();
  return () => controller.abort();
}
