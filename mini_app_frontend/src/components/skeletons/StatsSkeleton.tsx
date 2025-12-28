import React from 'react';
import { Skeleton } from './Skeleton';

export function StatsSkeleton(): React.ReactElement {
  return (
    <div className="stats-skeleton" aria-label="Loading statistics" role="status">
      {/* Navigation skeleton */}
      <div
        className="nav-skeleton"
        style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}
      >
        <Skeleton width={80} height={32} borderRadius={16} />
        <Skeleton width={60} height={32} borderRadius={16} />
        <Skeleton width={100} height={32} borderRadius={16} />
      </div>

      {/* Period selector */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
        <Skeleton width={60} height={36} borderRadius={8} />
        <Skeleton width={60} height={36} borderRadius={8} />
        <Skeleton width={60} height={36} borderRadius={8} />
      </div>

      {/* Total messages */}
      <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
        <Skeleton width={120} height={40} style={{ margin: '0 auto 0.5rem' }} />
        <Skeleton width={100} height={14} style={{ margin: '0 auto' }} />
      </div>

      {/* Verdict grid */}
      <div
        className="verdict-grid-skeleton"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '0.75rem',
          marginBottom: '1.5rem',
        }}
      >
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} style={{ textAlign: 'center' }}>
            <Skeleton width={40} height={24} style={{ margin: '0 auto 0.25rem' }} />
            <Skeleton width={60} height={12} style={{ margin: '0 auto' }} />
          </div>
        ))}
      </div>

      {/* FP Rate card */}
      <div
        className="fp-card-skeleton"
        style={{
          padding: '1rem',
          marginBottom: '1.5rem',
          background: 'var(--tg-theme-secondary-bg-color, #f0f0f0)',
          borderRadius: '12px',
        }}
      >
        <Skeleton width={80} height={16} style={{ marginBottom: '0.5rem' }} />
        <Skeleton width={60} height={28} style={{ marginBottom: '0.25rem' }} />
        <Skeleton width={140} height={12} />
      </div>

      {/* Threat types */}
      <div className="threats-skeleton">
        <Skeleton width={120} height={18} style={{ marginBottom: '0.75rem' }} />
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}
          >
            <Skeleton width={100} height={16} />
            <Skeleton width={30} height={16} />
          </div>
        ))}
      </div>
    </div>
  );
}
