import { useEffect, useCallback, useMemo } from 'react';
import type { TelegramWebApp, TelegramUser, TelegramThemeParams } from '../types';

interface UseTelegramResult {
  webApp: TelegramWebApp | undefined;
  user: TelegramUser | undefined;
  themeParams: TelegramThemeParams | undefined;
  colorScheme: 'light' | 'dark';
  isReady: boolean;
  close: () => void;
  showConfirm: (message: string) => Promise<boolean>;
  showAlert: (message: string) => Promise<void>;
  hapticFeedback: {
    impact: (style?: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
    notification: (type?: 'error' | 'success' | 'warning') => void;
    selection: () => void;
  };
  mainButton: {
    show: (text: string, onClick: () => void) => void;
    hide: () => void;
    showProgress: () => void;
    hideProgress: () => void;
    enable: () => void;
    disable: () => void;
  };
  backButton: {
    show: (onClick: () => void) => void;
    hide: () => void;
  };
  startParam: string | undefined;
}

export function useTelegram(): UseTelegramResult {
  const webApp = window.Telegram?.WebApp;

  useEffect(() => {
    if (webApp) {
      webApp.ready();
      webApp.expand();
    }
  }, [webApp]);

  const close = useCallback(() => {
    webApp?.close();
  }, [webApp]);

  const showConfirm = useCallback(
    (message: string): Promise<boolean> => {
      return new Promise((resolve) => {
        if (webApp?.showConfirm) {
          webApp.showConfirm(message, (confirmed) => {
            resolve(confirmed);
          });
        } else {
          // Fallback for non-Telegram environment
          resolve(window.confirm(message));
        }
      });
    },
    [webApp]
  );

  const showAlert = useCallback(
    (message: string): Promise<void> => {
      return new Promise((resolve) => {
        if (webApp?.showAlert) {
          webApp.showAlert(message, () => {
            resolve();
          });
        } else {
          window.alert(message);
          resolve();
        }
      });
    },
    [webApp]
  );

  const hapticFeedback = useMemo(
    () => ({
      impact: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft' = 'medium') => {
        webApp?.HapticFeedback?.impactOccurred(style);
      },
      notification: (type: 'error' | 'success' | 'warning' = 'success') => {
        webApp?.HapticFeedback?.notificationOccurred(type);
      },
      selection: () => {
        webApp?.HapticFeedback?.selectionChanged();
      },
    }),
    [webApp]
  );

  const mainButton = useMemo(() => {
    let currentHandler: (() => void) | null = null;

    return {
      show: (text: string, onClick: () => void) => {
        if (webApp?.MainButton) {
          if (currentHandler) {
            webApp.MainButton.offClick(currentHandler);
          }
          currentHandler = onClick;
          webApp.MainButton.setText(text);
          webApp.MainButton.onClick(onClick);
          webApp.MainButton.show();
        }
      },
      hide: () => {
        if (webApp?.MainButton) {
          if (currentHandler) {
            webApp.MainButton.offClick(currentHandler);
            currentHandler = null;
          }
          webApp.MainButton.hide();
        }
      },
      showProgress: () => {
        webApp?.MainButton?.showProgress(true);
      },
      hideProgress: () => {
        webApp?.MainButton?.hideProgress();
      },
      enable: () => {
        webApp?.MainButton?.enable();
      },
      disable: () => {
        webApp?.MainButton?.disable();
      },
    };
  }, [webApp]);

  const backButton = useMemo(() => {
    let currentHandler: (() => void) | null = null;

    return {
      show: (onClick: () => void) => {
        if (webApp?.BackButton) {
          if (currentHandler) {
            webApp.BackButton.offClick(currentHandler);
          }
          currentHandler = onClick;
          webApp.BackButton.onClick(onClick);
          webApp.BackButton.show();
        }
      },
      hide: () => {
        if (webApp?.BackButton) {
          if (currentHandler) {
            webApp.BackButton.offClick(currentHandler);
            currentHandler = null;
          }
          webApp.BackButton.hide();
        }
      },
    };
  }, [webApp]);

  return {
    webApp,
    user: webApp?.initDataUnsafe?.user,
    themeParams: webApp?.themeParams,
    colorScheme: webApp?.colorScheme || 'light',
    isReady: !!webApp,
    close,
    showConfirm,
    showAlert,
    hapticFeedback,
    mainButton,
    backButton,
    startParam: webApp?.initDataUnsafe?.start_param,
  };
}
