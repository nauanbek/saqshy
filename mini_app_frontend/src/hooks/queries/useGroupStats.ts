import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { getGroupStats } from '../../api/client';
import { queryKeys } from '../../lib/queryClient';
import type { GroupStats } from '../../types';

type UseGroupStatsOptions = Omit<UseQueryOptions<GroupStats, Error>, 'queryKey' | 'queryFn'>;

export function useGroupStats(
  groupId: number | null,
  periodDays: number = 7,
  options?: UseGroupStatsOptions
) {
  return useQuery({
    queryKey: queryKeys.groupStats(groupId ?? 0, periodDays),
    queryFn: () => getGroupStats(groupId!, periodDays),
    enabled: groupId !== null && groupId > 0,
    staleTime: 60 * 1000, // 1 minute - stats don't change that often
    ...options,
  });
}
