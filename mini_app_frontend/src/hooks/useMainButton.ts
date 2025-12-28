import { useEffect, useRef, useCallback } from 'react';
import { useTelegram } from './useTelegram';

interface UseMainButtonOptions {
  text: string;
  onClick: () => void | Promise<void>;
  visible?: boolean;
  enabled?: boolean;
  color?: string;
  textColor?: string;
  showProgress?: boolean;
}

export function useMainButton({
  text,
  onClick,
  visible = true,
  enabled = true,
  color,
  textColor,
  showProgress = false,
}: UseMainButtonOptions): void {
  const { webApp, hapticFeedback } = useTelegram();
  const onClickRef = useRef(onClick);
  const isProcessingRef = useRef(false);

  // Keep onClick ref updated
  useEffect(() => {
    onClickRef.current = onClick;
  }, [onClick]);

  // Wrapped handler with haptic feedback and loading state
  const handleClick = useCallback(async () => {
    if (isProcessingRef.current) return;

    const mainButton = webApp?.MainButton;
    if (!mainButton) return;

    isProcessingRef.current = true;
    hapticFeedback.impact('medium');

    // Show progress
    mainButton.showProgress(true);
    mainButton.disable();

    try {
      await onClickRef.current();
      hapticFeedback.notification('success');
    } catch {
      hapticFeedback.notification('error');
    } finally {
      mainButton.hideProgress();
      if (enabled) {
        mainButton.enable();
      }
      isProcessingRef.current = false;
    }
  }, [webApp, hapticFeedback, enabled]);

  // Setup MainButton
  useEffect(() => {
    const mainButton = webApp?.MainButton;
    if (!mainButton) return;

    // Set text
    mainButton.setText(text);

    // Set colors if provided
    if (color) {
      mainButton.color = color;
    }
    if (textColor) {
      mainButton.textColor = textColor;
    }

    // Set visibility
    if (visible) {
      mainButton.show();
    } else {
      mainButton.hide();
    }

    // Set enabled state
    if (enabled && !showProgress) {
      mainButton.enable();
    } else {
      mainButton.disable();
    }

    // Set progress state
    if (showProgress) {
      mainButton.showProgress(true);
    } else {
      mainButton.hideProgress();
    }

    // Attach click handler
    mainButton.onClick(handleClick);

    // Cleanup
    return () => {
      mainButton.offClick(handleClick);
    };
  }, [webApp, text, visible, enabled, color, textColor, showProgress, handleClick]);

  // Hide button on unmount
  useEffect(() => {
    return () => {
      webApp?.MainButton?.hide();
    };
  }, [webApp]);
}
