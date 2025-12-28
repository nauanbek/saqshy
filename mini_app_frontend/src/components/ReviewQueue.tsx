import React, { useState, useCallback, useRef, useEffect } from 'react';
import { FixedSizeList as List, ListChildComponentProps } from 'react-window';
import type { PendingReview } from '../types';
import { LoadingSpinner } from './LoadingSpinner';
import { useTelegram } from '../hooks/useTelegram';

// Estimated height of each review card (includes padding/margins)
const REVIEW_ITEM_HEIGHT = 180;

// Minimum height for the virtual list
const MIN_LIST_HEIGHT = 400;

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

function getRiskLabel(score: number): string {
  if (score >= 92) return 'Critical risk';
  if (score >= 75) return 'High risk';
  if (score >= 50) return 'Medium risk';
  if (score >= 30) return 'Low risk';
  return 'Safe';
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

function ReviewItem({ review, onApprove, onConfirmBlock }: ReviewItemProps): React.ReactElement {
  const { hapticFeedback, showConfirm } = useTelegram();
  const [actionLoading, setActionLoading] = useState<'approve' | 'block' | null>(null);

  const handleApprove = async () => {
    hapticFeedback.impact('light');
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
    hapticFeedback.impact('medium');
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

  const userName = review.username ? `@${review.username}` : `User ${review.user_id}`;

  return (
    <article className="review-item" aria-labelledby={`review-${review.id}-user`}>
      <div className="review-header">
        <div className="review-user">
          <span className="review-username" id={`review-${review.id}-user`}>
            {userName}
          </span>
          <span
            className="review-time"
            aria-label={`Submitted ${formatTimeAgo(review.created_at)}`}
          >
            {formatTimeAgo(review.created_at)}
          </span>
        </div>
        <div
          className={`risk-badge risk-${riskColor}`}
          role="img"
          aria-label={`${getRiskLabel(review.risk_score)}, score ${review.risk_score}`}
        >
          <span className="risk-score" aria-hidden="true">
            {review.risk_score}
          </span>
        </div>
      </div>

      <div className="review-message">
        <p>{truncateMessage(review.message_preview)}</p>
      </div>

      {review.threat_types.length > 0 && (
        <div className="review-threats" role="list" aria-label="Detected threat types">
          {review.threat_types.map((threat) => (
            <span key={threat} className="threat-tag" role="listitem">
              {threat}
            </span>
          ))}
        </div>
      )}

      <div className="review-actions" role="group" aria-label={`Actions for ${userName}`}>
        <button
          className="btn btn-success"
          onClick={handleApprove}
          disabled={actionLoading !== null}
          aria-label={`Approve message from ${userName}`}
          aria-busy={actionLoading === 'approve'}
        >
          {actionLoading === 'approve' ? <LoadingSpinner size="small" /> : 'Approve'}
        </button>
        <button
          className="btn btn-danger"
          onClick={handleConfirmBlock}
          disabled={actionLoading !== null}
          aria-label={`Block user ${userName}`}
          aria-busy={actionLoading === 'block'}
        >
          {actionLoading === 'block' ? <LoadingSpinner size="small" /> : 'Confirm Block'}
        </button>
      </div>
    </article>
  );
}

// Data passed to each virtualized row
interface RowData {
  reviews: PendingReview[];
  onApprove: (reviewId: string) => Promise<void>;
  onConfirmBlock: (reviewId: string) => Promise<void>;
}

// Virtualized row component for react-window
function ReviewRow({
  index,
  style,
  data,
}: ListChildComponentProps<RowData>): React.ReactElement | null {
  const review = data.reviews[index];

  // Safety check for noUncheckedIndexedAccess
  if (!review) {
    return null;
  }

  return (
    <div style={style}>
      <ReviewItem
        review={review}
        onApprove={() => data.onApprove(review.id)}
        onConfirmBlock={() => data.onConfirmBlock(review.id)}
      />
    </div>
  );
}

export function ReviewQueue({
  reviews,
  onApprove,
  onConfirmBlock,
  isLoading,
}: ReviewQueueProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const [listHeight, setListHeight] = useState(MIN_LIST_HEIGHT);

  // Calculate available height for the list
  useEffect(() => {
    const calculateHeight = () => {
      if (containerRef.current) {
        // Get viewport height minus header and padding
        const viewportHeight = window.innerHeight;
        const headerOffset = containerRef.current.getBoundingClientRect().top;
        const padding = 40; // Bottom padding
        const calculatedHeight = viewportHeight - headerOffset - padding;

        setListHeight(Math.max(MIN_LIST_HEIGHT, calculatedHeight));
      }
    };

    calculateHeight();
    window.addEventListener('resize', calculateHeight);

    return () => window.removeEventListener('resize', calculateHeight);
  }, []);

  // Memoize handlers to prevent unnecessary re-renders
  const handleApprove = useCallback((reviewId: string) => onApprove(reviewId), [onApprove]);

  const handleConfirmBlock = useCallback(
    (reviewId: string) => onConfirmBlock(reviewId),
    [onConfirmBlock]
  );

  if (isLoading) {
    return (
      <div className="review-queue-loading">
        <LoadingSpinner size="large" text="Loading reviews..." />
      </div>
    );
  }

  if (reviews.length === 0) {
    return (
      <div className="review-queue-empty" role="status" aria-live="polite">
        <div className="empty-icon" aria-hidden="true">
          [ok]
        </div>
        <h3>No pending reviews</h3>
        <p>All caught up! No messages need your attention right now.</p>
      </div>
    );
  }

  // Data object passed to each row - avoids re-creating on each render
  const itemData: RowData = {
    reviews,
    onApprove: handleApprove,
    onConfirmBlock: handleConfirmBlock,
  };

  return (
    <div className="review-queue" ref={containerRef} role="region" aria-label="Review queue">
      <div className="review-queue-header">
        <h3 id="review-queue-title">Pending Reviews</h3>
        <span className="review-count" aria-live="polite">
          {reviews.length} items
        </span>
      </div>

      <List
        height={listHeight}
        itemCount={reviews.length}
        itemSize={REVIEW_ITEM_HEIGHT}
        width="100%"
        itemData={itemData}
        overscanCount={3}
        className="review-list-virtual"
      >
        {ReviewRow}
      </List>
    </div>
  );
}
