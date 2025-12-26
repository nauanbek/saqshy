import React from 'react';

interface LoadingSpinnerProps {
  size?: 'small' | 'medium' | 'large';
  text?: string;
}

export function LoadingSpinner({
  size = 'medium',
  text,
}: LoadingSpinnerProps): React.ReactElement {
  const sizeMap = {
    small: 20,
    medium: 32,
    large: 48,
  };

  const spinnerSize = sizeMap[size];

  return (
    <div className="loading-spinner-container">
      <svg
        className="loading-spinner"
        width={spinnerSize}
        height={spinnerSize}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle
          className="loading-spinner-track"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="3"
          opacity="0.2"
        />
        <path
          className="loading-spinner-head"
          d="M12 2a10 10 0 0 1 10 10"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
      {text && <span className="loading-spinner-text">{text}</span>}
    </div>
  );
}
