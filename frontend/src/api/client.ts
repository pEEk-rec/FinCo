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
  ask: (text: string, clarification?: string) =>
    post<AskOut>('/ask', { text, clarification: clarification ?? null }),
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
