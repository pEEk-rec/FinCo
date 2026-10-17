import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api,
  ApiError,
  type CheckinResponse,
  type GoalIn,
  type GoalsOut,
  type GoalUpdateIn,
  type ReviewFeedback,
  type TransactionFilters,
} from './client';

/** Server state keys; one place so invalidation after a write is exact. */
export const keys = {
  session: ['session'] as const,
  dashboard: (period?: string) => ['dashboard', period ?? 'current'] as const,
  categories: ['categories'] as const,
  transactions: (f: TransactionFilters) => ['transactions', f] as const,
  transaction: (id: string | null) => ['transaction', id] as const,
  review: ['review-queue'] as const,
  consents: ['consents'] as const,
  imports: ['imports'] as const,
  monthly: (period: string, version?: number) => ['monthly', period, version ?? 'latest'] as const,
  timeline: ['timeline'] as const,
  alerts: ['alerts'] as const,
  goals: ['goals'] as const,
  coach: ['coach'] as const,
};

const retry = (count: number, error: Error) =>
  error instanceof ApiError && error.retryable ? count < 2 : false;

export const useSession = () => useQuery({ queryKey: keys.session, queryFn: api.session, retry });
export const useDashboard = (period?: string) =>
  useQuery({ queryKey: keys.dashboard(period), queryFn: () => api.dashboard(period), retry });
export const useCategories = () =>
  useQuery({ queryKey: keys.categories, queryFn: api.categories, staleTime: 60_000, retry });
export const useTransactions = (filters: TransactionFilters) =>
  useQuery({
    queryKey: keys.transactions(filters),
    queryFn: () => api.transactions(filters),
    placeholderData: (previous) => previous,
    retry,
  });
export const useTransaction = (id: string | null) =>
  useQuery({
    queryKey: keys.transaction(id),
    queryFn: () => api.transaction(id as string),
    enabled: id !== null,
    retry,
  });
export const useReviewQueue = () =>
  useQuery({ queryKey: keys.review, queryFn: api.reviewQueue, retry });
export const useConsents = () =>
  useQuery({ queryKey: keys.consents, queryFn: api.consents, retry });
export const useImports = () => useQuery({ queryKey: keys.imports, queryFn: api.imports, retry });
export const useMonthlyReview = (period: string, version?: number) =>
  useQuery({
    queryKey: keys.monthly(period, version),
    queryFn: () => api.monthlyReview(period, version),
    retry,
  });
export const useTimeline = () =>
  useQuery({ queryKey: keys.timeline, queryFn: api.timeline, retry });
export const useAlerts = () => useQuery({ queryKey: keys.alerts, queryFn: api.alerts, retry });
export const useGoals = () => useQuery({ queryKey: keys.goals, queryFn: api.goals, retry });

export const useCoach = () => useQuery({ queryKey: keys.coach, queryFn: api.coach, retry });

/** Every change to a challenge goes through the API; the whole coach view is then re-read. */
export function useCoachWrites() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: keys.coach });
  const run = <V>(fn: (v: V) => Promise<unknown>) => ({ mutationFn: fn, onSuccess: refresh });
  return {
    suggest: useMutation(run(() => api.suggestOffers())),
    accept: useMutation(run((id: string) => api.acceptOffer(id))),
    dismiss: useMutation(run((id: string) => api.dismissOffer(id))),
    acceptAdjustment: useMutation(run((id: string) => api.acceptAdjustment(id))),
    rejectAdjustment: useMutation(run((id: string) => api.rejectAdjustment(id))),
    pause: useMutation(run((id: string) => api.pauseExperiment(id))),
    resume: useMutation(run((id: string) => api.resumeExperiment(id))),
    abandon: useMutation(run((id: string) => api.abandonExperiment(id))),
    checkin: useMutation(
      run((v: { id: string; response: CheckinResponse }) => api.answerCheckin(v.id, v.response)),
    ),
    confirm: useMutation(run((id: string) => api.confirmIntegrity(id))),
    feedback: useMutation(
      run((v: { id: string; body: ReviewFeedback }) => api.sendFeedback(v.id, v.body)),
    ),
  };
}

/** Goal writes return the whole goals view, so the cache is replaced without a refetch. */
export function useGoalWrites() {
  const client = useQueryClient();
  const store = (data: GoalsOut) => client.setQueryData(keys.goals, data);
  return {
    create: useMutation({ mutationFn: (b: GoalIn) => api.createGoal(b), onSuccess: store }),
    update: useMutation({
      mutationFn: (v: { id: string; body: GoalUpdateIn }) => api.updateGoal(v.id, v.body),
      onSuccess: store,
    }),
    contribute: useMutation({
      mutationFn: (v: { id: string; paise: number }) => api.addToGoal(v.id, v.paise),
      onSuccess: store,
    }),
  };
}

/** After any write that changes money-relevant data, everything derived from it refetches. */
export function useInvalidateFinancials() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      [
        'dashboard',
        'transactions',
        'transaction',
        'review-queue',
        'monthly',
        'timeline',
        'alerts',
      ].map((key) => client.invalidateQueries({ queryKey: [key] })),
    );
}

export function useRecategorize() {
  const invalidate = useInvalidateFinancials();
  return useMutation({
    mutationFn: (v: { id: string; categoryId: string | null; remember: boolean }) =>
      api.recategorize(v.id, v.categoryId, v.remember),
    onSuccess: invalidate,
  });
}

/** Create a category of the user's own; the list refreshes everywhere. */
export function useCreateCategory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.createCategory(name),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.categories }),
  });
}

export function useUndo() {
  const invalidate = useInvalidateFinancials();
  return useMutation({
    mutationFn: (auditEventId: string) => api.undo(auditEventId),
    onSuccess: invalidate,
  });
}
