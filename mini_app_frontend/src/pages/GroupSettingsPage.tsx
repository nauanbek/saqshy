import React, { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { SettingsForm } from '../components';
import { SettingsSkeleton } from '../components/skeletons';
import { ErrorFallback } from '../components/ErrorBoundary';
import { useToast } from '../hooks/useToast';
import { useGroupSettings } from '../hooks/queries';
import { useUpdateSettings } from '../hooks/mutations';
import { useBackButton } from '../hooks/useBackButton';
import { useTelegram } from '../hooks/useTelegram';
import type { GroupSettings } from '../types';

interface GroupSettingsPageProps {
  groupId: number;
}

function GroupSettingsPage({ groupId }: GroupSettingsPageProps): React.ReactElement {
  const navigate = useNavigate();
  const { hapticFeedback } = useTelegram();
  const toast = useToast();

  // Hide back button on settings page (it's the main page)
  useBackButton({ visible: false });

  // Fetch settings with React Query
  const { data: settings, isLoading, error, refetch } = useGroupSettings(groupId);

  // Update settings mutation
  const updateMutation = useUpdateSettings();

  // Handle save with optimistic update
  const handleSave = useCallback(
    async (updatedSettings: Partial<GroupSettings>) => {
      try {
        await updateMutation.mutateAsync({
          groupId,
          settings: updatedSettings,
        });
        hapticFeedback.notification('success');
        toast.success('Settings saved successfully');
      } catch (err) {
        hapticFeedback.notification('error');
        const message = err instanceof Error ? err.message : 'Failed to save settings';
        toast.error(message);
        throw err;
      }
    },
    [groupId, updateMutation, hapticFeedback, toast]
  );

  // Loading state with skeleton
  if (isLoading) {
    return (
      <div className="page page-settings">
        <header className="page-header">
          <h1>Group Settings</h1>
          <nav className="page-nav">
            <button className="nav-link" disabled>
              View Stats
            </button>
            <button className="nav-link" disabled>
              Review Queue
            </button>
          </nav>
        </header>
        <main className="page-content">
          <SettingsSkeleton />
        </main>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="page page-settings">
        <header className="page-header">
          <h1>Group Settings</h1>
        </header>
        <main className="page-content">
          <ErrorFallback error={error} onRetry={() => refetch()} />
        </main>
      </div>
    );
  }

  // No data state
  if (!settings) {
    return (
      <div className="page page-error">
        <div className="error-card">
          <h2>Not Found</h2>
          <p>Group settings not found.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page page-settings">
      <header className="page-header">
        <h1>Group Settings</h1>
        <nav className="page-nav">
          <button
            className="nav-link"
            onClick={() => {
              hapticFeedback.impact('light');
              navigate('/stats');
            }}
          >
            View Stats
          </button>
          <button
            className="nav-link"
            onClick={() => {
              hapticFeedback.impact('light');
              navigate('/review');
            }}
          >
            Review Queue
          </button>
        </nav>
      </header>

      <main className="page-content">
        <SettingsForm settings={settings} onSave={handleSave} isSaving={updateMutation.isPending} />
      </main>
    </div>
  );
}

export default GroupSettingsPage;
