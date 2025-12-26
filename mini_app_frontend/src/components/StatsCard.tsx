import React from 'react';
import type { GroupStats } from '../types';

interface StatsCardProps {
  stats: GroupStats;
}

interface StatItemProps {
  label: string;
  value: number;
  color: 'green' | 'blue' | 'yellow' | 'orange' | 'red' | 'gray';
  total?: number;
}

function StatItem({ label, value, color, total }: StatItemProps): React.ReactElement {
  const percentage = total && total > 0 ? (value / total) * 100 : 0;

  return (
    <div className={`stat-item stat-${color}`}>
      <div className="stat-header">
        <span className="stat-label">{label}</span>
        <span className="stat-value">{value.toLocaleString()}</span>
      </div>
      {total && total > 0 && (
        <div className="stat-bar">
          <div
            className="stat-bar-fill"
            style={{ width: `${Math.min(percentage, 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

function FalsePositiveRate({
  fpRate,
  fpCount,
  blocked,
}: {
  fpRate: number;
  fpCount: number;
  blocked: number;
}): React.ReactElement {
  const rateColor =
    fpRate > 0.1 ? 'red' : fpRate > 0.05 ? 'yellow' : 'green';
  const ratePercent = (fpRate * 100).toFixed(1);

  return (
    <div className={`fp-rate-card fp-${rateColor}`}>
      <div className="fp-rate-header">
        <h4>False Positive Rate</h4>
        <span className="fp-rate-value">{ratePercent}%</span>
      </div>
      <p className="fp-rate-detail">
        {fpCount} admin overrides / {blocked} blocked
      </p>
      {fpRate > 0.1 && (
        <div className="fp-rate-warning">
          High FP rate! Consider adjusting sensitivity or checking whitelist.
        </div>
      )}
      {fpRate <= 0.05 && (
        <div className="fp-rate-success">
          FP rate is within target (&lt;5%)
        </div>
      )}
    </div>
  );
}

export function StatsCard({ stats }: StatsCardProps): React.ReactElement {
  const totalModerated =
    stats.allowed + stats.watched + stats.limited + stats.reviewed + stats.blocked;

  return (
    <div className="stats-card">
      <div className="stats-header">
        <h3>Moderation Stats</h3>
        <span className="stats-period">Last {stats.period_days} days</span>
      </div>

      <div className="stats-summary">
        <div className="stats-total">
          <span className="stats-total-value">
            {stats.total_messages.toLocaleString()}
          </span>
          <span className="stats-total-label">Total Messages</span>
        </div>
      </div>

      <div className="verdict-grid">
        <StatItem
          label="Allowed"
          value={stats.allowed}
          color="green"
          total={totalModerated}
        />
        <StatItem
          label="Watched"
          value={stats.watched}
          color="blue"
          total={totalModerated}
        />
        <StatItem
          label="Limited"
          value={stats.limited}
          color="yellow"
          total={totalModerated}
        />
        <StatItem
          label="Reviewed"
          value={stats.reviewed}
          color="orange"
          total={totalModerated}
        />
        <StatItem
          label="Blocked"
          value={stats.blocked}
          color="red"
          total={totalModerated}
        />
      </div>

      {stats.group_type === 'deals' && (
        <FalsePositiveRate
          fpRate={stats.fp_rate}
          fpCount={stats.fp_count}
          blocked={stats.blocked}
        />
      )}

      {stats.top_threat_types.length > 0 && (
        <div className="threat-types">
          <h4>Top Threat Types</h4>
          <div className="threat-list">
            {stats.top_threat_types.slice(0, 5).map((threat) => (
              <div key={threat.type} className="threat-row">
                <span className="threat-type">{threat.type}</span>
                <span className="threat-count">{threat.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
