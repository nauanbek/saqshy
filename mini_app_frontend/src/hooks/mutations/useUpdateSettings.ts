import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateGroupSettings } from '../../api/client';
import { queryKeys } from '../../lib/queryClient';
import type { GroupSettings } from '../../types';

interface UpdateSettingsVariables {
  groupId: number;
  settings: Partial<GroupSettings>;
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, settings }: UpdateSettingsVariables) =>
      updateGroupSettings(groupId, settings),

    // Optimistic update
    onMutate: async ({ groupId, settings }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({
        queryKey: queryKeys.groupSettings(groupId),
      });

      // Snapshot the previous value
      const previousSettings = queryClient.getQueryData<GroupSettings>(
        queryKeys.groupSettings(groupId)
      );

      // Optimistically update to the new value
      if (previousSettings) {
        queryClient.setQueryData(queryKeys.groupSettings(groupId), {
          ...previousSettings,
          ...settings,
          updated_at: new Date().toISOString(),
        });
      }

      return { previousSettings };
    },

    // If mutation fails, roll back
    onError: (_err, { groupId }, context) => {
      if (context?.previousSettings) {
        queryClient.setQueryData(queryKeys.groupSettings(groupId), context.previousSettings);
      }
    },

    // After success or error, refetch to get server state
    onSettled: (_data, _error, { groupId }) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.groupSettings(groupId),
      });
    },
  });
}
