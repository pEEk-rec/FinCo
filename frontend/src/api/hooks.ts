import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api,
  ApiError,
  type GoalIn,
  type GoalsOut,
  type GoalUpdateIn,
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
