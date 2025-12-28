import React, { useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LoadingSpinner } from './components';
import { ToastContainer } from './components/Toast';
import { OfflineBanner } from './components/OfflineBanner';
import { PageErrorBoundary } from './components/ErrorBoundary';
import { useTelegram } from './hooks/useTelegram';
import { useAppStore } from './stores';

// Lazy load pages for better initial load performance
const GroupSettingsPage = lazy(() => import('./pages/GroupSettingsPage'));
const GroupStatsPage = lazy(() => import('./pages/GroupStatsPage'));
const ReviewQueuePage = lazy(() => import('./pages/ReviewQueuePage'));

// Page loading fallback
function PageLoader(): React.ReactElement {
  return (
    <div className="page-loading">
      <LoadingSpinner size="large" text="Loading..." />
    </div>
  );
}

function AppContent(): React.ReactElement {
  const { isReady, startParam, colorScheme } = useTelegram();
  const { groupId, setGroupId, setColorScheme, initError, setInitError, setInitialized } =
    useAppStore();

  // Sync color scheme with Telegram
  useEffect(() => {
    setColorScheme(colorScheme);
  }, [colorScheme, setColorScheme]);

  // Parse group ID on mount
  useEffect(() => {
    let id: number | null = null;

    // Try to parse from start_param
    if (startParam) {
      // Handle formats: group_-123456789, group-123456789, or -123456789
      const match = startParam.match(/^group_?(-?\d+)$/);
      if (match && match[1]) {
        id = parseInt(match[1], 10);
      } else if (/^-?\d+$/.test(startParam)) {
        // Plain numeric ID (can be negative for groups/supergroups)
        id = parseInt(startParam, 10);
      }
    }

    // Fallback: check URL search params for development
    if (!id) {
      const urlParams = new URLSearchParams(window.location.search);
      const groupParam = urlParams.get('group_id');
      // Telegram group IDs are negative for groups/supergroups
      if (groupParam && /^-?\d+$/.test(groupParam)) {
        id = parseInt(groupParam, 10);
      }
    }

    if (id && !isNaN(id)) {
      setGroupId(id);
      setInitialized(true);
    } else {
      setInitError('No group ID provided. Please open this app from a group settings.');
      setInitialized(true);
    }
  }, [startParam, setGroupId, setInitError, setInitialized]);

  if (!isReady) {
    return (
      <div className="app-loading">
        <LoadingSpinner size="large" text="Initializing..." />
      </div>
    );
  }

  if (initError) {
    return (
      <div className="app-error">
        <div className="error-card">
          <h2>Configuration Error</h2>
          <p>{initError}</p>
          <p className="error-hint">Open this Mini App from a group where the bot is admin.</p>
        </div>
      </div>
    );
  }

  if (!groupId) {
    return (
      <div className="app-loading">
        <LoadingSpinner size="large" text="Loading group..." />
      </div>
    );
  }

  return (
    <>
      <OfflineBanner />
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route
            path="/"
            element={
              <PageErrorBoundary>
                <GroupSettingsPage groupId={groupId} />
              </PageErrorBoundary>
            }
          />
          <Route
            path="/stats"
            element={
              <PageErrorBoundary>
                <GroupStatsPage groupId={groupId} />
              </PageErrorBoundary>
            }
          />
          <Route
            path="/review"
            element={
              <PageErrorBoundary>
                <ReviewQueuePage groupId={groupId} />
              </PageErrorBoundary>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      <ToastContainer />
    </>
  );
}

export function App(): React.ReactElement {
  return (
    <BrowserRouter basename="/app">
      <AppContent />
    </BrowserRouter>
  );
}
