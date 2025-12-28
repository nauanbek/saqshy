import React from 'react';

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  borderRadius?: string | number;
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({
  width = '100%',
  height = '1rem',
  borderRadius = '4px',
  className = '',
  style,
}: SkeletonProps): React.ReactElement {
  return (
    <div
      className={`skeleton ${className}`}
      style={{
        width: typeof width === 'number' ? `${width}px` : width,
        height: typeof height === 'number' ? `${height}px` : height,
        borderRadius: typeof borderRadius === 'number' ? `${borderRadius}px` : borderRadius,
        ...style,
      }}
      aria-hidden="true"
    />
  );
}

// Text skeleton with random width variation
interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

export function SkeletonText({ lines = 1, className = '' }: SkeletonTextProps): React.ReactElement {
  const widths = ['100%', '90%', '95%', '85%', '80%'];

  return (
    <div className={`skeleton-text ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          width={widths[i % widths.length]}
          height="0.875rem"
          style={{ marginBottom: i < lines - 1 ? '0.5rem' : 0 }}
        />
      ))}
    </div>
  );
}

// Circle skeleton for avatars
interface SkeletonCircleProps {
  size?: number;
  className?: string;
}

export function SkeletonCircle({
  size = 40,
  className = '',
}: SkeletonCircleProps): React.ReactElement {
  return <Skeleton width={size} height={size} borderRadius="50%" className={className} />;
}

// Button skeleton
interface SkeletonButtonProps {
  width?: string | number;
  className?: string;
}

export function SkeletonButton({
  width = '100px',
  className = '',
}: SkeletonButtonProps): React.ReactElement {
  return <Skeleton width={width} height="36px" borderRadius="8px" className={className} />;
}
