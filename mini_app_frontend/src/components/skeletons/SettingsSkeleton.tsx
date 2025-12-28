import React from 'react';
import { Skeleton, SkeletonText } from './Skeleton';

export function SettingsSkeleton(): React.ReactElement {
  return (
    <div className="settings-skeleton" aria-label="Loading settings" role="status">
      {/* Navigation skeleton */}
      <div
        className="nav-skeleton"
        style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}
      >
        <Skeleton width={60} height={32} borderRadius={16} />
        <Skeleton width={80} height={32} borderRadius={16} />
        <Skeleton width={100} height={32} borderRadius={16} />
      </div>

      {/* Group Type Section */}
      <div className="settings-section-skeleton" style={{ marginBottom: '1.5rem' }}>
        <Skeleton width={100} height={20} style={{ marginBottom: '0.75rem' }} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
          <Skeleton height={60} borderRadius={8} />
          <Skeleton height={60} borderRadius={8} />
          <Skeleton height={60} borderRadius={8} />
          <Skeleton height={60} borderRadius={8} />
        </div>
      </div>

      {/* Linked Channel Section */}
      <div className="settings-section-skeleton" style={{ marginBottom: '1.5rem' }}>
        <Skeleton width={120} height={20} style={{ marginBottom: '0.75rem' }} />
        <Skeleton height={44} borderRadius={8} style={{ marginBottom: '0.5rem' }} />
        <SkeletonText lines={1} />
      </div>

      {/* Sandbox Section */}
      <div className="settings-section-skeleton" style={{ marginBottom: '1.5rem' }}>
        <Skeleton width={100} height={20} style={{ marginBottom: '0.75rem' }} />
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '0.75rem',
          }}
        >
          <Skeleton width={140} height={16} />
          <Skeleton width={44} height={24} borderRadius={12} />
        </div>
        <Skeleton height={8} borderRadius={4} style={{ marginBottom: '0.5rem' }} />
        <SkeletonText lines={1} />
      </div>

      {/* Notifications Section */}
      <div className="settings-section-skeleton" style={{ marginBottom: '1.5rem' }}>
        <Skeleton width={110} height={20} style={{ marginBottom: '0.75rem' }} />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Skeleton width={160} height={16} />
          <Skeleton width={44} height={24} borderRadius={12} />
        </div>
      </div>
    </div>
  );
}
