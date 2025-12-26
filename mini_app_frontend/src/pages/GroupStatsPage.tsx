import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StatsCard, LoadingSpinner } from '../components';
import { getGroupStats } from '../api/client';
import { useTelegram } from '../hooks/useTelegram';
import type { GroupStats } from '../types';

interface GroupStatsPageProps {
  groupId: number;
}

const PERIOD_OPTIONS = [
  { value: 7, label: '7 days' },
  { value: 14, label: '14 days' },
  { value: 30, label: '30 days' },
];

export function GroupStatsPage({
  groupId,
}: GroupStatsPageProps): React.ReactElement {
  const navigate = useNavigate();
  const { backButton, hapticFeedback } = useTelegram();

  const [stats, setStats] = useState<GroupStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodDays, setPeriodDays] = useState(7);

  // Load stats
  useEffect(() => {
    async function loadStats() {
      setIsLoading(true);
      setError(null);

      try {
        const data = await getGroupStats(groupId, periodDays);
        setStats(data);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Failed to load statistics';
        setError(message);
      } finally {
        setIsLoading(false);
      }
    }

    loadStats();
  }, [groupId, periodDays]);

  // Setup back button
  useEffect(() => {
    backButton.show(() => {
      navigate('/app');
    });

    return () => {
      backButton.hide();
    };
  }, [backButton, navigate]);

  const handlePeriodChange = (days: number) => {
    hapticFeedback.selection();
    setPeriodDays(days);
  };

  if (isLoading) {
    return (
      <div className="page page-loading">
        <LoadingSpinner size="large" text="Loading statistics..." />
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

  if (!stats) {
    return (
      <div className="page page-error">
        <div className="error-card">
          <h2>No Data</h2>
          <p>No statistics available for this group.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page page-stats">
      <header className="page-header">
        <h1>Statistics</h1>
        <div className="period-selector">
          {PERIOD_OPTIONS.map((option) => (
            <button
              key={option.value}
              className={`period-btn ${
                periodDays === option.value ? 'active' : ''
              }`}
              onClick={() => handlePeriodChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      <main className="page-content">
        <StatsCard stats={stats} />

        <div className="stats-actions">
          <button
            className="btn btn-secondary"
            onClick={() => navigate('/app')}
          >
            Back to Settings
          </button>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/app/review')}
          >
            Review Queue
          </button>
        </div>
      </main>
    </div>
  );
}
