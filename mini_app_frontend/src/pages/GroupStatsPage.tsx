import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StatsCard } from '../components';
import { StatsSkeleton } from '../components/skeletons';
import { ErrorFallback } from '../components/ErrorBoundary';
import { useGroupStats } from '../hooks/queries';
import { useBackButton } from '../hooks/useBackButton';
import { useTelegram } from '../hooks/useTelegram';

interface GroupStatsPageProps {
  groupId: number;
}

const PERIOD_OPTIONS = [
  { value: 7, label: '7 days' },
  { value: 14, label: '14 days' },
  { value: 30, label: '30 days' },
];

function GroupStatsPage({ groupId }: GroupStatsPageProps): React.ReactElement {
  const navigate = useNavigate();
  const { hapticFeedback } = useTelegram();
  const [periodDays, setPeriodDays] = useState(7);

  // Setup back button to go to settings
  useBackButton({ navigateTo: '/' });

  // Fetch stats with React Query
  const { data: stats, isLoading, error, refetch } = useGroupStats(groupId, periodDays);

  const handlePeriodChange = (days: number) => {
    hapticFeedback.selection();
    setPeriodDays(days);
  };

  // Loading state with skeleton
  if (isLoading) {
    return (
      <div className="page page-stats">
        <header className="page-header">
          <h1>Statistics</h1>
          <div className="period-selector">
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={`period-btn ${periodDays === option.value ? 'active' : ''}`}
                onClick={() => handlePeriodChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </header>
        <main className="page-content">
          <StatsSkeleton />
        </main>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="page page-stats">
        <header className="page-header">
          <h1>Statistics</h1>
        </header>
        <main className="page-content">
          <ErrorFallback error={error} onRetry={() => refetch()} />
        </main>
      </div>
    );
  }

  // No data state
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
              className={`period-btn ${periodDays === option.value ? 'active' : ''}`}
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
            onClick={() => {
              hapticFeedback.impact('light');
              navigate('/');
            }}
          >
            Back to Settings
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              hapticFeedback.impact('light');
              navigate('/review');
            }}
          >
            Review Queue
          </button>
        </div>
      </main>
    </div>
  );
}

export default GroupStatsPage;
