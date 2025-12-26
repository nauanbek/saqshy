import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { SettingsForm, LoadingSpinner } from '../components';
import { getGroupSettings, updateGroupSettings } from '../api/client';
import { useTelegram } from '../hooks/useTelegram';
import type { GroupSettings } from '../types';

interface GroupSettingsPageProps {
  groupId: number;
}

export function GroupSettingsPage({
  groupId,
}: GroupSettingsPageProps): React.ReactElement {
  const navigate = useNavigate();
  const { backButton } = useTelegram();

  const [settings, setSettings] = useState<GroupSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load settings
  useEffect(() => {
    async function loadSettings() {
      setIsLoading(true);
      setError(null);

      try {
        const data = await getGroupSettings(groupId);
        setSettings(data);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Failed to load settings';
        setError(message);
      } finally {
        setIsLoading(false);
      }
    }

    loadSettings();
  }, [groupId]);

  // Setup back button
  useEffect(() => {
    backButton.hide();
    return () => {
      backButton.hide();
    };
  }, [backButton]);

  // Handle save
  const handleSave = useCallback(
    async (updatedSettings: Partial<GroupSettings>) => {
      setIsSaving(true);

      try {
        const newSettings = await updateGroupSettings(groupId, updatedSettings);
        setSettings(newSettings);
      } finally {
        setIsSaving(false);
      }
    },
    [groupId]
  );

  if (isLoading) {
    return (
      <div className="page page-loading">
        <LoadingSpinner size="large" text="Loading settings..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page page-error">
        <div className="error-card">
          <h2>Error</h2>
          <p>{error}</p>
          <button
            className="btn btn-primary"
            onClick={() => window.location.reload()}
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

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
            onClick={() => navigate('/app/stats')}
          >
            View Stats
          </button>
          <button
            className="nav-link"
            onClick={() => navigate('/app/review')}
          >
            Review Queue
          </button>
        </nav>
      </header>

      <main className="page-content">
        <SettingsForm
          settings={settings}
          onSave={handleSave}
          isSaving={isSaving}
        />
      </main>
    </div>
  );
}
