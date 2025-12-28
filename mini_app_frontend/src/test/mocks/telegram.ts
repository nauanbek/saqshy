import { vi } from 'vitest';

export function createMockTelegramWebApp(overrides: Partial<typeof window.Telegram.WebApp> = {}) {
  return {
    initData: 'mock_init_data',
    initDataUnsafe: {
      user: {
        id: 123456789,
        first_name: 'Test',
        last_name: 'User',
        username: 'testuser',
        language_code: 'en',
      },
      start_param: 'group_123',
    },
    themeParams: {
      bg_color: '#ffffff',
      text_color: '#000000',
      hint_color: '#999999',
      link_color: '#2678b6',
      button_color: '#50a8eb',
      button_text_color: '#ffffff',
      secondary_bg_color: '#f0f0f0',
    },
    colorScheme: 'light' as const,
    isExpanded: false,
    viewportHeight: 600,
    viewportStableHeight: 600,
    headerColor: '#ffffff',
    backgroundColor: '#ffffff',
    ready: vi.fn(),
    expand: vi.fn(),
    close: vi.fn(),
    showConfirm: vi.fn((message: string, callback: (confirmed: boolean) => void) => callback(true)),
    showAlert: vi.fn((message: string, callback?: () => void) => callback?.()),
    MainButton: {
      text: '',
      color: '#50a8eb',
      textColor: '#ffffff',
      isVisible: false,
      isActive: true,
      isProgressVisible: false,
      setText: vi.fn(),
      onClick: vi.fn(),
      offClick: vi.fn(),
      show: vi.fn(),
      hide: vi.fn(),
      enable: vi.fn(),
      disable: vi.fn(),
      showProgress: vi.fn(),
      hideProgress: vi.fn(),
    },
    BackButton: {
      isVisible: false,
      onClick: vi.fn(),
      offClick: vi.fn(),
      show: vi.fn(),
      hide: vi.fn(),
    },
    HapticFeedback: {
      impactOccurred: vi.fn(),
      notificationOccurred: vi.fn(),
      selectionChanged: vi.fn(),
    },
    ...overrides,
  };
}

export function mockTelegramWebApp(overrides: Partial<typeof window.Telegram.WebApp> = {}) {
  const webApp = createMockTelegramWebApp(overrides);
  vi.stubGlobal('Telegram', { WebApp: webApp });
  return webApp;
}
