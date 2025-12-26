import React, { useEffect, useState } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';
import { GroupSettingsPage, GroupStatsPage, ReviewQueuePage } from './pages';
import { LoadingSpinner } from './components';
import { useTelegram } from './hooks/useTelegram';

function AppContent(): React.ReactElement {
  const { isReady, startParam } = useTelegram();
  const [groupId, setGroupId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Parse group ID from start_param or URL
    // Format: group_12345 or just 12345
    let id: number | null = null;

    if (startParam) {
      const match = startParam.match(/^group_?(\d+)$/);
      if (match) {
        id = parseInt(match[1], 10);
      } else if (/^\d+$/.test(startParam)) {
        id = parseInt(startParam, 10);
      }
    }

    // Fallback: check URL search params for development
    if (!id) {
      const urlParams = new URLSearchParams(window.location.search);
      const groupParam = urlParams.get('group_id');
      if (groupParam && /^\d+$/.test(groupParam)) {
        id = parseInt(groupParam, 10);
      }
    }

    if (id && !isNaN(id)) {
      setGroupId(id);
    } else {
      setError(
        'No group ID provided. Please open this app from a group settings.'
      );
    }
  }, [startParam]);

  if (!isReady) {
    return (
      <div className="app-loading">
        <LoadingSpinner size="large" text="Initializing..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-error">
        <div className="error-card">
          <h2>Configuration Error</h2>
          <p>{error}</p>
          <p className="error-hint">
            Open this Mini App from a group where the bot is admin.
          </p>
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
    <Routes>
      <Route
        path="/app"
        element={<GroupSettingsPage groupId={groupId} />}
      />
      <Route
        path="/app/stats"
        element={<GroupStatsPage groupId={groupId} />}
      />
      <Route
        path="/app/review"
        element={<ReviewQueuePage groupId={groupId} />}
      />
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

export function App(): React.ReactElement {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}
