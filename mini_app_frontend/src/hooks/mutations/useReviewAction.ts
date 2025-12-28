import { useMutation, useQueryClient } from '@tanstack/react-query';
import { submitReviewAction } from '../../api/client';
import { queryKeys } from '../../lib/queryClient';
import type { PendingReview, ReviewAction } from '../../types';

interface ReviewActionVariables {
  groupId: number;
  action: ReviewAction;
}

export function useReviewAction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, action }: ReviewActionVariables) => submitReviewAction(groupId, action),

    // Optimistic update - remove the review from list immediately
    onMutate: async ({ groupId, action }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({
        queryKey: queryKeys.reviews(groupId),
      });

      // Snapshot the previous value
      const previousReviews = queryClient.getQueryData<PendingReview[]>(queryKeys.reviews(groupId));

      // Optimistically remove the review
      if (previousReviews) {
        queryClient.setQueryData(
          queryKeys.reviews(groupId),
          previousReviews.filter((r) => r.id !== action.review_id)
        );
      }

      return { previousReviews };
    },

    // If mutation fails, roll back
    onError: (_err, { groupId }, context) => {
      if (context?.previousReviews) {
        queryClient.setQueryData(queryKeys.reviews(groupId), context.previousReviews);
      }
    },

    // After success, also invalidate stats as they might have changed
    onSettled: (_data, _error, { groupId }) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.reviews(groupId),
      });
      // Stats might be affected by the review action
      queryClient.invalidateQueries({
        queryKey: queryKeys.group(groupId),
        predicate: (query) => query.queryKey.includes('stats'),
      });
    },
  });
}
