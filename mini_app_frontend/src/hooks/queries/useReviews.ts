import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { getPendingReviews } from '../../api/client';
import { queryKeys } from '../../lib/queryClient';
import type { PendingReview } from '../../types';

type UseReviewsOptions = Omit<UseQueryOptions<PendingReview[], Error>, 'queryKey' | 'queryFn'>;

export function useReviews(groupId: number | null, options?: UseReviewsOptions) {
  return useQuery({
    queryKey: queryKeys.reviews(groupId ?? 0),
    queryFn: () => getPendingReviews(groupId!),
    enabled: groupId !== null && groupId !== 0,
    staleTime: 10 * 1000, // 10 seconds - reviews change frequently
    refetchInterval: 30 * 1000, // Auto-refetch every 30 seconds
    ...options,
  });
}
