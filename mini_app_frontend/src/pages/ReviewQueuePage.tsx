import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ReviewQueue, LoadingSpinner } from '../components';
import { getPendingReviews, submitReviewAction } from '../api/client';
import { useTelegram } from '../hooks/useTelegram';
import type { PendingReview } from '../types';

interface ReviewQueuePageProps {
  groupId: number;
}

export function ReviewQueuePage({
  groupId,
}: ReviewQueuePageProps): React.ReactElement {
  const navigate = useNavigate();
  const { backButton, showAlert } = useTelegram();

  const [reviews, setReviews] = useState<PendingReview[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  // Load reviews
  const loadReviews = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const data = await getPendingReviews(groupId);
      setReviews(data);
      setLastRefresh(new Date());
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to load reviews';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [groupId]);

  useEffect(() => {
    loadReviews();
  }, [loadReviews]);

  // Setup back button
  useEffect(() => {
    backButton.show(() => {
      navigate('/app');
    });

    return () => {
      backButton.hide();
    };
  }, [backButton, navigate]);

  // Handle approve
  const handleApprove = useCallback(
    async (reviewId: string) => {
      try {
        await submitReviewAction(groupId, {
          review_id: reviewId,
          action: 'approve',
        });

        // Remove from local state
        setReviews((prev) => prev.filter((r) => r.id !== reviewId));
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Failed to approve message';
        await showAlert(`Error: ${message}`);
        throw err;
      }
    },
    [groupId, showAlert]
  );

  // Handle confirm block
  const handleConfirmBlock = useCallback(
    async (reviewId: string) => {
      try {
        await submitReviewAction(groupId, {
          review_id: reviewId,
          action: 'confirm_block',
        });

        // Remove from local state
        setReviews((prev) => prev.filter((r) => r.id !== reviewId));
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Failed to confirm block';
        await showAlert(`Error: ${message}`);
        throw err;
      }
    },
    [groupId, showAlert]
  );

  if (error) {
    return (
      <div className="page page-error">
        <div className="error-card">
          <h2>Error</h2>
          <p>{error}</p>
          <button className="btn btn-primary" onClick={loadReviews}>
            Try Again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page page-review">
      <header className="page-header">
        <h1>Review Queue</h1>
        <div className="header-actions">
          <span className="last-refresh">
            Updated {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            className="btn btn-icon"
            onClick={loadReviews}
            disabled={isLoading}
            title="Refresh"
          >
            {isLoading ? <LoadingSpinner size="small" /> : '[refresh]'}
          </button>
        </div>
      </header>

      <main className="page-content">
        <ReviewQueue
          reviews={reviews}
          onApprove={handleApprove}
          onConfirmBlock={handleConfirmBlock}
          isLoading={isLoading}
        />

        <div className="review-actions">
          <button
            className="btn btn-secondary"
            onClick={() => navigate('/app')}
          >
            Back to Settings
          </button>
        </div>
      </main>
    </div>
  );
}
