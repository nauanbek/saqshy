import { test as base, Page } from '@playwright/test';

// Mock Telegram WebApp for E2E tests
export async function mockTelegramWebApp(page: Page, options: {
  groupId?: number;
  userId?: number;
  username?: string;
  colorScheme?: 'light' | 'dark';
} = {}) {
  const {
    groupId = 123,
    userId = 123456789,
    username = 'testuser',
    colorScheme = 'light',
  } = options;

  await page.addInitScript(({ groupId, userId, username, colorScheme }) => {
    (window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: {
        initData: 'mock_init_data_for_e2e',
        initDataUnsafe: {
          user: {
            id: userId,
            first_name: 'Test',
            last_name: 'User',
            username: username,
            language_code: 'en',
          },
          start_param: `group_${groupId}`,
        },
        themeParams: {
          bg_color: colorScheme === 'dark' ? '#1c1c1e' : '#ffffff',
          text_color: colorScheme === 'dark' ? '#ffffff' : '#000000',
          hint_color: colorScheme === 'dark' ? '#98989f' : '#999999',
          link_color: '#2678b6',
          button_color: '#50a8eb',
          button_text_color: '#ffffff',
          secondary_bg_color: colorScheme === 'dark' ? '#2c2c2e' : '#f0f0f0',
        },
        colorScheme: colorScheme,
        isExpanded: false,
        viewportHeight: 600,
        viewportStableHeight: 600,
        headerColor: colorScheme === 'dark' ? '#1c1c1e' : '#ffffff',
        backgroundColor: colorScheme === 'dark' ? '#1c1c1e' : '#ffffff',
        ready: () => {},
        expand: () => {},
        close: () => {},
        showConfirm: (message: string, callback: (confirmed: boolean) => void) => {
          callback(true);
        },
        showAlert: (message: string, callback?: () => void) => {
          callback?.();
        },
        MainButton: {
          text: '',
          color: '#50a8eb',
          textColor: '#ffffff',
          isVisible: false,
          isActive: true,
          isProgressVisible: false,
          setText: () => {},
          onClick: () => {},
          offClick: () => {},
          show: () => {},
          hide: () => {},
          enable: () => {},
          disable: () => {},
          showProgress: () => {},
          hideProgress: () => {},
        },
        BackButton: {
          isVisible: false,
          onClick: () => {},
          offClick: () => {},
          show: () => {},
          hide: () => {},
        },
        HapticFeedback: {
          impactOccurred: () => {},
          notificationOccurred: () => {},
          selectionChanged: () => {},
        },
      },
    };
  }, { groupId, userId, username, colorScheme });
}

// Extended test with Telegram mock
export const test = base.extend<{ telegramPage: Page }>({
  telegramPage: async ({ page }, use) => {
    await mockTelegramWebApp(page);
    await use(page);
  },
});

export { expect } from '@playwright/test';
