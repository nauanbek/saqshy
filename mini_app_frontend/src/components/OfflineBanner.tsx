import React from 'react';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

export function OfflineBanner(): React.ReactElement | null {
  const isOnline = useOnlineStatus();

  if (isOnline) {
    return null;
  }

  return (
    <div className="offline-banner" role="alert" aria-live="assertive">
      <span className="offline-icon">📡</span>
      <span className="offline-message">You're offline. Some features may not work.</span>
    </div>
  );
}
