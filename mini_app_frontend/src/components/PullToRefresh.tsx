import React, { useRef, useState, useCallback, useEffect } from 'react';
import { useTelegram } from '../hooks/useTelegram';

interface PullToRefreshProps {
  onRefresh: () => Promise<void>;
  children: React.ReactNode;
  disabled?: boolean;
  threshold?: number;
}

const PULL_THRESHOLD = 80; // pixels to pull before refresh triggers
const MAX_PULL = 120; // maximum pull distance

export function PullToRefresh({
  onRefresh,
  children,
  disabled = false,
  threshold = PULL_THRESHOLD,
}: PullToRefreshProps): React.ReactElement {
  const { hapticFeedback } = useTelegram();
  const containerRef = useRef<HTMLDivElement>(null);
  const [pullDistance, setPullDistance] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [startY, setStartY] = useState<number | null>(null);
  const [triggered, setTriggered] = useState(false);

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (disabled || isRefreshing) return;

      // Only start pull if at top of scroll
      const container = containerRef.current;
      const firstTouch = e.touches[0];
      if (container && container.scrollTop === 0 && firstTouch) {
        setStartY(firstTouch.clientY);
      }
    },
    [disabled, isRefreshing]
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (startY === null || disabled || isRefreshing) return;

      const firstTouch = e.touches[0];
      if (!firstTouch) return;

      const currentY = firstTouch.clientY;
      const diff = currentY - startY;

      if (diff > 0) {
        // Pulling down - apply resistance
        const distance = Math.min(diff * 0.5, MAX_PULL);
        setPullDistance(distance);

        // Trigger haptic when crossing threshold
        if (distance >= threshold && !triggered) {
          hapticFeedback.impact('light');
          setTriggered(true);
        } else if (distance < threshold && triggered) {
          setTriggered(false);
        }
      }
    },
    [startY, disabled, isRefreshing, threshold, triggered, hapticFeedback]
  );

  const handleTouchEnd = useCallback(async () => {
    if (startY === null || disabled) return;

    if (pullDistance >= threshold && !isRefreshing) {
      setIsRefreshing(true);
      hapticFeedback.notification('success');

      try {
        await onRefresh();
      } finally {
        setIsRefreshing(false);
      }
    }

    setPullDistance(0);
    setStartY(null);
    setTriggered(false);
  }, [startY, pullDistance, threshold, isRefreshing, disabled, onRefresh, hapticFeedback]);

  // Reset state if disabled changes
  useEffect(() => {
    if (disabled) {
      setPullDistance(0);
      setStartY(null);
      setTriggered(false);
    }
  }, [disabled]);

  const indicatorOpacity = Math.min(pullDistance / threshold, 1);
  const indicatorScale = 0.5 + indicatorOpacity * 0.5;
  const shouldShowIndicator = pullDistance > 10 || isRefreshing;

  return (
    <div
      ref={containerRef}
      className="pull-to-refresh-container"
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      {/* Pull indicator */}
      <div
        className="pull-to-refresh-indicator"
        style={{
          opacity: shouldShowIndicator ? indicatorOpacity : 0,
          transform: `translateY(${pullDistance - 40}px) scale(${indicatorScale})`,
        }}
      >
        <div className={`pull-spinner ${isRefreshing ? 'spinning' : ''}`}>
          {isRefreshing ? '...' : pullDistance >= threshold ? '[ok]' : '[v]'}
        </div>
        <span className="pull-text">
          {isRefreshing
            ? 'Refreshing...'
            : pullDistance >= threshold
              ? 'Release to refresh'
              : 'Pull to refresh'}
        </span>
      </div>

      {/* Content with transform */}
      <div
        className="pull-to-refresh-content"
        style={{
          transform: `translateY(${pullDistance}px)`,
          transition: startY === null ? 'transform 0.2s ease-out' : 'none',
        }}
      >
        {children}
      </div>
    </div>
  );
}
