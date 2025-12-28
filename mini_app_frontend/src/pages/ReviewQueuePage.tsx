import React, { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ReviewQueue, LoadingSpinner, PullToRefresh } from '../components';
import { ReviewQueueSkeleton } from '../components/skeletons';
import { ErrorFallback } from '../components/ErrorBoundary';
import { useToast } from '../hooks/useToast';
import { useReviews } from '../hooks/queries';
import { useReviewAction } from '../hooks/mutations';
import { useBackButton } from '../hooks/useBackButton';
import { useTelegram } from '../hooks/useTelegram';

interface ReviewQueuePageProps {
  groupId: number;
}

function ReviewQueuePage({ groupId }: ReviewQueuePageProps): React.ReactElement {
  const navigate = useNavigate();
  const { hapticFeedback } = useTelegram();
  const toast = useToast();

  // Setup back button to go to settings
  useBackButton({ navigateTo: '/' });

  // Fetch reviews with React Query (auto-refetch every 30s)
  const {
    data: reviews = [],
    isLoading,
    isFetching,
    error,
    refetch,
    dataUpdatedAt,
  } = useReviews(groupId);

  // Review action mutation
  const actionMutation = useReviewAction();

  // Format last update time
  const lastRefresh = dataUpdatedAt ? new Date(dataUpdatedAt) : new Date();

  // Handle approve
  const handleApprove = useCallback(
    async (reviewId: string) => {
      try {
        await actionMutation.mutateAsync({
          groupId,
          action: { review_id: reviewId, action: 'approve' },
        });
        hapticFeedback.notification('success');
        toast.success('Message approved');
      } catch (err) {
        hapticFeedback.notification('error');
        const message = err instanceof Error ? err.message : 'Failed to approve';
        toast.error(message);
        throw err;
      }
    },
    [groupId, actionMutation, hapticFeedback, toast]
  );

  // Handle confirm block
  const handleConfirmBlock = useCallback(
    async (reviewId: string) => {
      try {
        await actionMutation.mutateAsync({
          groupId,
          action: { review_id: reviewId, action: 'confirm_block' },
        });
        hapticFeedback.notification('success');
        toast.success('Block confirmed');
      } catch (err) {
        hapticFeedback.notification('error');
        const message = err instanceof Error ? err.message : 'Failed to confirm block';
        toast.error(message);
        throw err;
      }
    },
    [groupId, actionMutation, hapticFeedback, toast]
  );

  // Initial loading state with skeleton
  if (isLoading) {
    return (
      <div className="page page-review">
        <header className="page-header">
          <h1>Review Queue</h1>
        </header>
        <main className="page-content">
          <ReviewQueueSkeleton />
        </main>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="page page-review">
        <header className="page-header">
          <h1>Review Queue</h1>
        </header>
        <main className="page-content">
          <ErrorFallback error={error} onRetry={() => refetch()} />
        </main>
      </div>
    );
  }

  return (
    <div className="page page-review">
      <header className="page-header">
        <h1>Review Queue</h1>
        <div className="header-actions">
          <span className="last-refresh">Updated {lastRefresh.toLocaleTimeString()}</span>
          <button
            className="btn btn-icon"
            onClick={() => {
              hapticFeedback.impact('light');
              refetch();
            }}
            disabled={isFetching}
            title="Refresh"
            aria-label="Refresh reviews"
          >
            {isFetching ? <LoadingSpinner size="small" /> : '↻'}
          </button>
        </div>
      </header>

      <main className="page-content">
        <PullToRefresh
          onRefresh={async () => {
            await refetch();
          }}
          disabled={isFetching}
        >
          <ReviewQueue
            reviews={reviews}
            onApprove={handleApprove}
            onConfirmBlock={handleConfirmBlock}
            isLoading={isFetching && reviews.length === 0}
          />
        </PullToRefresh>

        <div className="review-actions">
          <button
            className="btn btn-secondary"
            onClick={() => {
              hapticFeedback.impact('light');
              navigate('/');
            }}
          >
            Back to Settings
          </button>
        </div>
      </main>
    </div>
  );
}

export default ReviewQueuePage;
