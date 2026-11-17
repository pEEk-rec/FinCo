import { parseSse } from './captureStream';
import { ApiError, getToken, type AskOut } from './client';

/** One thing the agent did, as it did it. */
export interface AgentStep {
  stage: string;
  title: string;
  detail?: string;
  /** Milliseconds since the run started. */
  ms: number;
  tone?: 'stop' | 'ok';
  /** For a tool step: which tool, whether it worked, and what it found. */
  tool?: string;
  ok?: boolean;
  step_seq?: number;
  data?: Record<string, unknown> | null;
  /** For the plan step: the tools it chose and why. */
  steps?: { seq: number; tool_name: string; rationale: string; proposed_by: string }[];
}

export interface AskStreamOptions {
  text: string;
  clarification?: string;
  useLlm?: boolean;
  signal?: AbortSignal;
  onStep: (step: AgentStep) => void;
}

/**
 * Ask a question and watch the agent work: every step is handed to `onStep` the moment the server
 * sends it, and the promise resolves with the finished result (the same shape as a plain ask).
 */
export async function streamAsk({
  text,
  clarification,
  useLlm = true,
  signal,
  onStep,
}: AskStreamOptions): Promise<AskOut> {
  let response: Response;
  try {
    response = await fetch('/api/ask/stream', {
      method: 'POST',
      signal,
      headers: {
        Authorization: `Bearer ${getToken() ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text, clarification: clarification ?? null, use_llm: useLlm }),
    });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError('UNREACHABLE', 'The service did not respond.', 0, true);
  }
  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status}).`;
    let code = 'HTTP_ERROR';
    try {
      const data = (await response.json()) as { code?: string; message?: string };
      code = data.code ?? code;
      message = data.message ?? message;
    } catch {
      /* not JSON: keep the generic message */
    }
    throw new ApiError(code, message, response.status, response.status >= 500);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: AskOut | null = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: !done });
    const { frames, rest } = parseSse(buffer);
    buffer = rest;
    for (const frame of frames) {
      if (frame.event === 'step') onStep(frame.data as AgentStep);
      else if (frame.event === 'result') result = frame.data as AskOut;
      else if (frame.event === 'error')
        throw new ApiError(
          'AGENT_FAILED',
          String((frame.data as { message?: string }).message ?? 'The agent could not finish.'),
          500,
          true,
        );
    }
    if (done) break;
  }
  if (!result) throw new ApiError('AGENT_FAILED', 'The answer did not arrive.', 500, true);
  return result;
}
