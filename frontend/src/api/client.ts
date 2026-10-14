import type { components } from './schema';

/** Every API type comes from the generated schema; nothing is hand-duplicated. */
type S = components['schemas'];
export type Dashboard = S['Dashboard'];
export type BudgetPace = S['BudgetPace'];
export type CategoryRow = S['CategoryRow'];
export type TransactionPage = S['TransactionPage'];
export type TransactionRow = S['TransactionRow'];
export type TransactionDetail = S['TransactionDetail'];
export type HistoryEntry = S['HistoryEntry'];
export type ReviewQueue = S['ReviewQueue'];
export type ReviewItem = S['ReviewItem'];
export type ConsentView = S['ConsentView'];
export type ImportResult = S['ImportResult'];
export type ImportBatchView = S['ImportBatchView'];
export type MonthlyReviewOut = S['MonthlyReviewOut'];
export type AdviceExplanation = S['AdviceExplanation'];
export type AskOut = S['AskOut'];
/** Live-mode routes exist only when the backend runs `copilot.live`, so they are typed by hand. */
export type LivePaceRow = {
  category_id: string;
  category_name: string;
  limit: string;
  limit_paise: number;
  percent_settled: number;
  percent_provisional: number;
  settled: string;
  provisional: string;
  total: string;
  projected: string;
  projected_percent: number;
  status: string;
  message: string;
};
export type LivePacing = {
  period: string;
  headline: string;
  rows: LivePaceRow[];
  provisional_count: number;
};
export type LiveEvent = {
  id: string;
  status: string;
  direction: string;
  amount: string;
  merchant: string;
  category_name: string | null;
  needs_review: boolean;
};
export type LiveStatus = {
  live: boolean;
  counts: { transactions: number; needs_review: number; alerts_waiting: number };
  webhook: { path: string; secret: string };
  aa: { configured: boolean; gateway: string | null; note: string };
};
export type LiveImport = {
  source: string;
  read: number;
  inserted: number;
  skipped_existing: number;
  needs_review: number;
  unreadable: number;
  unreadable_examples: string[];
  verified_alerts: number;
  still_provisional: number;
};
export type LiveReceipt = {
  outcome: string;
  reason: string | null;
  receipt_id: string | null;
  merchant: string | null;
  parts: { id: string; category_name: string | null; category_id: string; amount: string }[];
};
export type LlmStatus = { available: boolean; router: Record<string, unknown> | null };
export type InvestigationOut = S['InvestigationOut'];
export type Session = S['Session'];
export type CategoryOut = S['CategoryOut'];
export type RecategorizeOut = S['RecategorizeOut'];
export type Timeline = S['Timeline'];
export type GoalsOut = S['GoalsOut'];
export type WhatIfOut = S['WhatIfOut'];
export type CompareOut = S['CompareOut'];
export type WhatIfIn = S['WhatIfIn'];
export type AlertDecisionIn = S['AlertDecisionIn'];

/** Failure with the API's stable error code. */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly retryable = false,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const TOKEN_KEY = 'finco.token';

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // storage unavailable: the token is simply not remembered
  }
}

/** Pick up `#token=...` from the URL printed by `copilot serve`, then clear it. */
export function captureTokenFromHash(): void {
  const match = /[#&]token=([^&]+)/.exec(window.location.hash);
  if (match?.[1]) {
    setToken(decodeURIComponent(match[1]));
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${getToken() ?? ''}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('UNREACHABLE', 'The service did not respond.', 0, true);
  }
  if (response.ok) return (await response.json()) as T;
  let code = 'HTTP_ERROR';
  let message = `Request failed (${response.status}).`;
  let retryable = false;
  try {
    const data = (await response.json()) as Partial<S['ApiError']>;
    code = data.code ?? code;
    message = data.message ?? message;
    retryable = data.retryable ?? false;
  } catch {
    if (response.status >= 500) code = 'UNREACHABLE';
  }
  throw new ApiError(code, message, response.status, retryable);
}

const get = <T>(path: string) => request<T>('GET', path);
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body);

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  );
  return entries.length
    ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString()}`
    : '';
}

export interface TransactionFilters {
  period?: string;
  category_id?: string;
  uncategorised?: boolean;
  needs_review?: boolean;
  source?: string;
  q?: string;
  offset?: number;
  limit?: number;
}

export const api = {
  session: () => get<Session>('/session'),
  dashboard: (period?: string) => get<Dashboard>(`/dashboard${qs({ period })}`),
  categories: () => get<CategoryOut[]>('/categories'),
  transactions: (f: TransactionFilters) => get<TransactionPage>(`/transactions${qs({ ...f })}`),
  transaction: (id: string) => get<TransactionDetail>(`/transactions/${encodeURIComponent(id)}`),
  reviewQueue: () => get<ReviewQueue>('/review-queue'),
  recategorize: (id: string, categoryId: string | null, remember: boolean) =>
    post<RecategorizeOut>(`/transactions/${encodeURIComponent(id)}/category`, {
      category_id: categoryId,
      remember,
    }),
  undo: (auditEventId: string) => post<S['UndoOut']>('/undo', { audit_event_id: auditEventId }),
  consents: () => get<ConsentView[]>('/consents'),
  imports: () => get<ImportBatchView[]>('/imports'),
  approveConsent: (id: string) => post<S['ConsentDecisionOut']>(`/consents/${id}/approve`),
  revokeConsent: (id: string) => post<S['ConsentDecisionOut']>(`/consents/${id}/revoke`),
  runImport: (id: string) => post<ImportResult>(`/consents/${id}/import`),
  monthlyReview: (period: string, version?: number) =>
    get<MonthlyReviewOut>(`/monthly-reviews/${period}${qs({ version })}`),
  generateReview: (period: string) => post<MonthlyReviewOut>('/monthly-reviews', { period }),
  advice: (id: string) => get<AdviceExplanation>(`/advice/${encodeURIComponent(id)}`),
  decideAdvice: (id: string, decision: 'approved' | 'rejected') =>
    post<S['AdviceDecisionOut']>(`/advice/${encodeURIComponent(id)}/decision`, { decision }),
  ask: (text: string, clarification?: string, useLlm = true) =>
    post<AskOut>('/ask', { text, clarification: clarification ?? null, use_llm: useLlm }),
  llmStatus: () => get<LlmStatus>('/llm/status'),
  live: {
    status: () => get<LiveStatus>('/live/status'),
    pacing: () => get<LivePacing>('/live/pacing'),
    events: () => get<LiveEvent[]>('/live/events'),
    importStatement: (text: string, filename?: string) =>
      post<LiveImport>('/live/import/statement', { text, filename: filename ?? null }),
    reconcile: () => post<{ verified: number; still_provisional: number }>('/live/reconcile'),
    receipt: (text: string) => post<LiveReceipt>('/live/receipt', { text }),
    decideSplit: (id: string, decision: 'approved' | 'rejected') =>
      post<Record<string, unknown>>(`/live/splits/${encodeURIComponent(id)}/decision`, {
        decision,
      }),
    aaConsent: (mobile: string) =>
      post<{ id: string; url: string; status: string }>('/live/aa/consent', { mobile }),
    aaStatus: (id: string) => get<{ id: string; status: string }>(`/live/aa/consent/${id}`),
    aaFetch: (consentId: string) => post<LiveImport>('/live/aa/fetch', { consent_id: consentId }),
  },
  timeline: () => get<Timeline>('/timeline'),
  alerts: () => get<S['AlertsOut']>('/alerts'),
  decideAlert: (id: string, body: AlertDecisionIn) =>
    post<Record<string, unknown>>(`/alerts/${id}/decision`, body),
  goals: () => get<GoalsOut>('/goals'),
  anomalies: () => get<S['AnomalyOut'][]>('/anomalies'),
  investigateAnomaly: (anomalyId: string) =>
    post<S['InvestigationOut']>('/investigate/anomaly', { anomaly_id: anomalyId }),
  investigateChange: (period: string, categoryId: string | null) =>
    post<S['InvestigationOut']>('/investigate/change', { period, category_id: categoryId }),
  whatIf: (body: WhatIfIn) => post<WhatIfOut>('/whatif', body),
  compare: (scenarios: WhatIfIn[]) => post<CompareOut>('/whatif/compare', { scenarios }),
};
