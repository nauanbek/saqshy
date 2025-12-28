import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { getGroupSettings } from '../../api/client';
import { queryKeys } from '../../lib/queryClient';
import type { GroupSettings } from '../../types';

type UseGroupSettingsOptions = Omit<UseQueryOptions<GroupSettings, Error>, 'queryKey' | 'queryFn'>;

export function useGroupSettings(groupId: number | null, options?: UseGroupSettingsOptions) {
  return useQuery({
    queryKey: queryKeys.groupSettings(groupId ?? 0),
    queryFn: () => getGroupSettings(groupId!),
    enabled: groupId !== null && groupId > 0,
    staleTime: 30 * 1000, // 30 seconds
    ...options,
  });
}
