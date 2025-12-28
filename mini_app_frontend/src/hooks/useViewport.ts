import { useState, useEffect, useCallback } from 'react';

interface ViewportState {
  height: number;
  stableHeight: number;
  isExpanded: boolean;
  isKeyboardVisible: boolean;
}

interface UseViewportResult extends ViewportState {
  expand: () => void;
}

/**
 * Hook to track Telegram WebApp viewport changes.
 * Handles virtual keyboard appearance and viewport expansion.
 */
export function useViewport(): UseViewportResult {
  const webApp = window.Telegram?.WebApp;

  const [viewport, setViewport] = useState<ViewportState>(() => ({
    height: webApp?.viewportHeight || window.innerHeight,
    stableHeight: webApp?.viewportStableHeight || window.innerHeight,
    isExpanded: webApp?.isExpanded || false,
    isKeyboardVisible: false,
  }));

  useEffect(() => {
    if (!webApp) return;

    const handleViewportChanged = (event: { isStateStable: boolean }) => {
      const newHeight = webApp.viewportHeight || window.innerHeight;
      const newStableHeight = webApp.viewportStableHeight || window.innerHeight;

      // Keyboard is likely visible if viewport height is significantly less than stable height
      const isKeyboardVisible = newStableHeight - newHeight > 100;

      setViewport({
        height: newHeight,
        stableHeight: newStableHeight,
        isExpanded: webApp.isExpanded || false,
        isKeyboardVisible,
      });

      // Only log in development
      if (import.meta.env.DEV) {
        console.log('[Viewport]', {
          height: newHeight,
          stableHeight: newStableHeight,
          isStable: event.isStateStable,
          isKeyboardVisible,
        });
      }
    };

    // Subscribe to viewport changes
    webApp.onEvent('viewportChanged', handleViewportChanged);

    // Set initial state
    setViewport({
      height: webApp.viewportHeight || window.innerHeight,
      stableHeight: webApp.viewportStableHeight || window.innerHeight,
      isExpanded: webApp.isExpanded || false,
      isKeyboardVisible: false,
    });

    return () => {
      webApp.offEvent('viewportChanged', handleViewportChanged);
    };
  }, [webApp]);

  const expand = useCallback(() => {
    webApp?.expand();
  }, [webApp]);

  return {
    ...viewport,
    expand,
  };
}

/**
 * Hook to apply CSS custom property for safe keyboard handling.
 * Sets --viewport-height CSS variable that updates on viewport changes.
 */
export function useViewportCSSProperty(): void {
  const { height } = useViewport();

  useEffect(() => {
    document.documentElement.style.setProperty('--viewport-height', `${height}px`);

    return () => {
      document.documentElement.style.removeProperty('--viewport-height');
    };
  }, [height]);
}
