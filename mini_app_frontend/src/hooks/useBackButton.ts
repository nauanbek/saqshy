import { useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTelegram } from './useTelegram';

interface UseBackButtonOptions {
  visible?: boolean;
  onClick?: () => void;
  navigateTo?: string;
}

export function useBackButton({
  visible = true,
  onClick,
  navigateTo,
}: UseBackButtonOptions = {}): void {
  const { webApp, hapticFeedback } = useTelegram();
  const navigate = useNavigate();
  const onClickRef = useRef(onClick);

  // Keep onClick ref updated
  useEffect(() => {
    onClickRef.current = onClick;
  }, [onClick]);

  // Wrapped handler with haptic feedback
  const handleClick = useCallback(() => {
    hapticFeedback.impact('light');

    if (onClickRef.current) {
      onClickRef.current();
    } else if (navigateTo) {
      navigate(navigateTo);
    } else {
      // Default: go back in history
      navigate(-1);
    }
  }, [hapticFeedback, navigate, navigateTo]);

  // Setup BackButton
  useEffect(() => {
    const backButton = webApp?.BackButton;
    if (!backButton) return;

    // Set visibility
    if (visible) {
      backButton.show();
    } else {
      backButton.hide();
    }

    // Attach click handler
    backButton.onClick(handleClick);

    // Cleanup
    return () => {
      backButton.offClick(handleClick);
    };
  }, [webApp, visible, handleClick]);

  // Hide button on unmount
  useEffect(() => {
    return () => {
      webApp?.BackButton?.hide();
    };
  }, [webApp]);
}
