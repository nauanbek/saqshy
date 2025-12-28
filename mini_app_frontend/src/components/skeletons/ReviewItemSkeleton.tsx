import React from 'react';
import { Skeleton, SkeletonCircle, SkeletonText, SkeletonButton } from './Skeleton';

export function ReviewItemSkeleton(): React.ReactElement {
  return (
    <div
      className="review-item-skeleton"
      style={{
        padding: '1rem',
        borderBottom: '1px solid var(--tg-theme-hint-color, #ccc)',
      }}
      aria-hidden="true"
    >
      {/* Header with user info */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}
      >
        <SkeletonCircle size={32} />
        <div style={{ flex: 1 }}>
          <Skeleton width={120} height={16} style={{ marginBottom: '0.25rem' }} />
          <Skeleton width={80} height={12} />
        </div>
        <Skeleton width={50} height={20} borderRadius={10} />
      </div>

      {/* Message preview */}
      <div style={{ marginBottom: '0.75rem' }}>
        <SkeletonText lines={2} />
      </div>

      {/* Tags */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <Skeleton width={60} height={22} borderRadius={11} />
        <Skeleton width={50} height={22} borderRadius={11} />
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
        <SkeletonButton width={80} />
        <SkeletonButton width={100} />
      </div>
    </div>
  );
}

export function ReviewQueueSkeleton(): React.ReactElement {
  return (
    <div className="review-queue-skeleton" aria-label="Loading reviews" role="status">
      {/* Navigation skeleton */}
      <div
        className="nav-skeleton"
        style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}
      >
        <Skeleton width={80} height={32} borderRadius={16} />
        <Skeleton width={60} height={32} borderRadius={16} />
        <Skeleton width={100} height={32} borderRadius={16} />
      </div>

      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1rem',
        }}
      >
        <Skeleton width={120} height={20} />
        <Skeleton width={80} height={32} borderRadius={8} />
      </div>

      {/* Review items */}
      <div>
        {[1, 2, 3].map((i) => (
          <ReviewItemSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}
