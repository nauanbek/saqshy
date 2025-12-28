import React, { Component, ErrorInfo, ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error for debugging
    console.error('ErrorBoundary caught an error:', error, errorInfo);

    // Call optional error handler
    this.props.onError?.(error, errorInfo);
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      // Use custom fallback if provided
      if (typeof this.props.fallback === 'function') {
        return this.props.fallback(this.state.error, this.reset);
      }

      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default fallback
      return <ErrorFallback error={this.state.error} onRetry={this.reset} />;
    }

    return this.props.children;
  }
}

// Default error fallback component
interface ErrorFallbackProps {
  error: Error;
  onRetry?: () => void;
}

export function ErrorFallback({ error, onRetry }: ErrorFallbackProps): React.ReactElement {
  const isNetworkError = error.name === 'NetworkError' || error.name === 'TimeoutError';

  return (
    <div className="error-fallback" role="alert">
      <div className="error-fallback-icon">{isNetworkError ? '📡' : '⚠️'}</div>
      <h2 className="error-fallback-title">
        {isNetworkError ? 'Connection Problem' : 'Something Went Wrong'}
      </h2>
      <p className="error-fallback-message">
        {isNetworkError
          ? 'Please check your internet connection and try again.'
          : error.message || 'An unexpected error occurred.'}
      </p>
      {onRetry && (
        <button className="btn btn-primary error-fallback-retry" onClick={onRetry}>
          Try Again
        </button>
      )}
      {import.meta.env.DEV && (
        <details className="error-fallback-details">
          <summary>Error Details</summary>
          <pre>{error.stack}</pre>
        </details>
      )}
    </div>
  );
}

// Convenience wrapper for page-level error boundaries
export function PageErrorBoundary({ children }: { children: ReactNode }): React.ReactElement {
  return (
    <ErrorBoundary
      fallback={(error, reset) => (
        <div className="page">
          <ErrorFallback error={error} onRetry={reset} />
        </div>
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
