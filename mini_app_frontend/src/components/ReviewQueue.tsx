import React, { useState } from 'react';
import type { PendingReview } from '../types';
import { LoadingSpinner } from './LoadingSpinner';
import { useTelegram } from '../hooks/useTelegram';

interface ReviewQueueProps {
  reviews: PendingReview[];
  onApprove: (reviewId: string) => Promise<void>;
  onConfirmBlock: (reviewId: string) => Promise<void>;
  isLoading: boolean;
}

interface ReviewItemProps {
  review: PendingReview;
  onApprove: () => Promise<void>;
  onConfirmBlock: () => Promise<void>;
}

function getRiskColor(score: number): string {
  if (score >= 92) return 'critical';
  if (score >= 75) return 'high';
  if (score >= 50) return 'medium';
  if (score >= 30) return 'low';
  return 'safe';
}

function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

function truncateMessage(message: string, maxLength: number = 150): string {
  if (message.length <= maxLength) return message;
  return message.substring(0, maxLength) + '...';
}

function ReviewItem({
  review,
  onApprove,
  onConfirmBlock,
}: ReviewItemProps): React.ReactElement {
  const { hapticFeedback, showConfirm } = useTelegram();
  const [actionLoading, setActionLoading] = useState<'approve' | 'block' | null>(
    null
  );

  const handleApprove = async () => {
    const confirmed = await showConfirm(
      'Approve this message? The user will be allowed to continue posting.'
    );
    if (!confirmed) return;

    setActionLoading('approve');
    try {
      await onApprove();
      hapticFeedback.notification('success');
    } catch {
      hapticFeedback.notification('error');
    } finally {
      setActionLoading(null);
    }
  };

  const handleConfirmBlock = async () => {
    const confirmed = await showConfirm(
      'Confirm block? The user will be permanently banned from the group.'
    );
    if (!confirmed) return;

    setActionLoading('block');
    try {
      await onConfirmBlock();
      hapticFeedback.notification('success');
    } catch {
      hapticFeedback.notification('error');
    } finally {
      setActionLoading(null);
    }
  };

  const riskColor = getRiskColor(review.risk_score);

  return (
    <div className="review-item">
      <div className="review-header">
        <div className="review-user">
          <span className="review-username">
            {review.username ? `@${review.username}` : `User ${review.user_id}`}
          </span>
          <span className="review-time">{formatTimeAgo(review.created_at)}</span>
        </div>
        <div className={`risk-badge risk-${riskColor}`}>
          <span className="risk-score">{review.risk_score}</span>
        </div>
      </div>

      <div className="review-message">
        <p>{truncateMessage(review.message_preview)}</p>
      </div>

      {review.threat_types.length > 0 && (
        <div className="review-threats">
          {review.threat_types.map((threat) => (
            <span key={threat} className="threat-tag">
              {threat}
            </span>
          ))}
        </div>
      )}

      <div className="review-actions">
        <button
          className="btn btn-success"
          onClick={handleApprove}
          disabled={actionLoading !== null}
        >
          {actionLoading === 'approve' ? (
            <LoadingSpinner size="small" />
          ) : (
            'Approve'
          )}
        </button>
        <button
          className="btn btn-danger"
          onClick={handleConfirmBlock}
          disabled={actionLoading !== null}
        >
          {actionLoading === 'block' ? (
            <LoadingSpinner size="small" />
          ) : (
            'Confirm Block'
          )}
        </button>
      </div>
    </div>
  );
}

export function ReviewQueue({
  reviews,
  onApprove,
  onConfirmBlock,
  isLoading,
}: ReviewQueueProps): React.ReactElement {
  if (isLoading) {
    return (
      <div className="review-queue-loading">
        <LoadingSpinner size="large" text="Loading reviews..." />
      </div>
    );
  }

  if (reviews.length === 0) {
    return (
      <div className="review-queue-empty">
        <div className="empty-icon">[ok]</div>
        <h3>No pending reviews</h3>
        <p>All caught up! No messages need your attention right now.</p>
      </div>
    );
  }

  return (
    <div className="review-queue">
      <div className="review-queue-header">
        <h3>Pending Reviews</h3>
        <span className="review-count">{reviews.length} items</span>
      </div>

      <div className="review-list">
        {reviews.map((review) => (
          <ReviewItem
            key={review.id}
            review={review}
            onApprove={() => onApprove(review.id)}
            onConfirmBlock={() => onConfirmBlock(review.id)}
          />
        ))}
      </div>
    </div>
  );
}
