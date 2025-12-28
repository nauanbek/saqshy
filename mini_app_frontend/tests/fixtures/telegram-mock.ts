import { Page } from '@playwright/test';

/**
 * Mock Telegram user for testing
 */
export interface MockTelegramUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
}

/**
 * Default test user
 */
export const defaultTestUser: MockTelegramUser = {
  id: 123456789,
  first_name: 'Test',
  last_name: 'User',
  username: 'testuser',
  language_code: 'en',
  is_premium: false,
};

/**
 * Generate mock initData string similar to Telegram WebApp format
 */
export function generateMockInitData(
  user: MockTelegramUser,
  groupId: number,
  isAdmin: boolean = false
): string {
  const params = new URLSearchParams({
    user: JSON.stringify(user),
    auth_date: Math.floor(Date.now() / 1000).toString(),
    hash: 'mock_hash_for_testing_e2e_12345',
    start_param: `group_${groupId}${isAdmin ? '_admin' : ''}`,
  });
  return params.toString();
}

/**
 * Inject Telegram WebApp mock into the page before navigation
 *
 * @param page - Playwright Page instance
 * @param user - Mock user data
 * @param groupId - Group ID (negative for supergroups)
 * @param isAdmin - Whether user is admin
 */
export async function injectTelegramWebApp(
  page: Page,
  user: MockTelegramUser = defaultTestUser,
  groupId: number = -1001234567890,
  isAdmin: boolean = true
): Promise<void> {
  const initData = generateMockInitData(user, groupId, isAdmin);
  const startParam = `group_${groupId}${isAdmin ? '_admin' : ''}`;

  // Intercept the Telegram SDK and replace it with our mock
  await page.route('**/telegram.org/js/telegram-web-app.js', async (route) => {
    // Return empty script - we'll set up our own mock
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: '// Telegram SDK blocked for testing',
    });
  });

  await page.addInitScript(
    (data: { initData: string; user: MockTelegramUser; startParam: string }) => {
      // Track callbacks for MainButton and BackButton
      let mainButtonCallback: (() => void) | null = null;
      let backButtonCallback: (() => void) | null = null;

      // Track confirm/alert callbacks for test automation
      const pendingConfirms: Array<(confirmed: boolean) => void> = [];
      const pendingAlerts: Array<() => void> = [];

      // Expose methods for test automation
      (window as unknown as Record<string, unknown>).__telegramTestHelpers = {
        confirmDialog: (accept: boolean) => {
          const cb = pendingConfirms.shift();
          if (cb) cb(accept);
        },
        dismissAlert: () => {
          const cb = pendingAlerts.shift();
          if (cb) cb();
        },
        clickMainButton: () => {
          if (mainButtonCallback) mainButtonCallback();
        },
        clickBackButton: () => {
          if (backButtonCallback) backButtonCallback();
        },
      };

      // Create mock Telegram WebApp
      (window as unknown as Record<string, unknown>).Telegram = {
        WebApp: {
          initData: data.initData,
          initDataUnsafe: {
            query_id: 'test_query_id',
            user: data.user,
            auth_date: Math.floor(Date.now() / 1000),
            hash: 'mock_hash_for_testing',
            start_param: data.startParam,
          },
          themeParams: {
            bg_color: '#ffffff',
            text_color: '#000000',
            hint_color: '#999999',
            link_color: '#2678b6',
            button_color: '#50a8eb',
            button_text_color: '#ffffff',
            secondary_bg_color: '#f0f0f0',
            header_bg_color: '#ffffff',
            accent_text_color: '#2678b6',
            section_bg_color: '#ffffff',
            section_header_text_color: '#6d6d72',
            subtitle_text_color: '#999999',
            destructive_text_color: '#ff3b30',
          },
          colorScheme: 'light',
          isExpanded: true,
          viewportHeight: 600,
          viewportStableHeight: 600,
          headerColor: '#ffffff',
          backgroundColor: '#ffffff',
          ready: () => {
            console.log('[TelegramMock] WebApp ready called');
          },
          expand: () => {
            console.log('[TelegramMock] WebApp expand called');
          },
          close: () => {
            console.log('[TelegramMock] WebApp close called');
          },
          showConfirm: (message: string, callback: (confirmed: boolean) => void) => {
            console.log('[TelegramMock] showConfirm:', message);
            // Auto-confirm for tests unless overridden
            pendingConfirms.push(callback);
            // Auto-confirm after a short delay if not handled
            setTimeout(() => {
              if (pendingConfirms.includes(callback)) {
                pendingConfirms.splice(pendingConfirms.indexOf(callback), 1);
                callback(true);
              }
            }, 100);
          },
          showAlert: (message: string, callback?: () => void) => {
            console.log('[TelegramMock] showAlert:', message);
            if (callback) {
              pendingAlerts.push(callback);
              // Auto-dismiss after a short delay
              setTimeout(() => {
                if (pendingAlerts.includes(callback)) {
                  pendingAlerts.splice(pendingAlerts.indexOf(callback), 1);
                  callback();
                }
              }, 100);
            }
          },
          onEvent: (eventType: string, callback: () => void) => {
            console.log('[TelegramMock] onEvent:', eventType);
          },
          offEvent: (eventType: string, callback: () => void) => {
            console.log('[TelegramMock] offEvent:', eventType);
          },
          MainButton: {
            text: '',
            color: '#50a8eb',
            textColor: '#ffffff',
            isVisible: false,
            isActive: true,
            isProgressVisible: false,
            setText: function (text: string) {
              this.text = text;
            },
            onClick: (callback: () => void) => {
              mainButtonCallback = callback;
            },
            offClick: (callback: () => void) => {
              if (mainButtonCallback === callback) {
                mainButtonCallback = null;
              }
            },
            show: function () {
              this.isVisible = true;
            },
            hide: function () {
              this.isVisible = false;
            },
            enable: function () {
              this.isActive = true;
            },
            disable: function () {
              this.isActive = false;
            },
            showProgress: function (leaveActive?: boolean) {
              this.isProgressVisible = true;
              if (!leaveActive) this.isActive = false;
            },
            hideProgress: function () {
              this.isProgressVisible = false;
              this.isActive = true;
            },
          },
          BackButton: {
            isVisible: false,
            onClick: (callback: () => void) => {
              backButtonCallback = callback;
            },
            offClick: (callback: () => void) => {
              if (backButtonCallback === callback) {
                backButtonCallback = null;
              }
            },
            show: function () {
              this.isVisible = true;
            },
            hide: function () {
              this.isVisible = false;
            },
          },
          HapticFeedback: {
            impactOccurred: (style: string) => {
              console.log('[TelegramMock] HapticFeedback.impactOccurred:', style);
            },
            notificationOccurred: (type: string) => {
              console.log('[TelegramMock] HapticFeedback.notificationOccurred:', type);
            },
            selectionChanged: () => {
              console.log('[TelegramMock] HapticFeedback.selectionChanged');
            },
          },
        },
      };
    },
    { initData, user, startParam }
  );
}

/**
 * Mock API responses for the Mini App
 */
export async function mockApiResponses(page: Page, groupId: number = -1001234567890): Promise<void> {
  // Mock group settings endpoint
  await page.route(`**/api/groups/${groupId}/settings`, async (route) => {
    const method = route.request().method();

    if (method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: groupId,
            group_type: 'general',
            linked_channel_id: null,
            sandbox_enabled: false,
            sandbox_duration_hours: 24,
            admin_notifications: true,
            sensitivity: 5,
            admin_alert_chat_id: null,
            custom_whitelist: [],
            custom_blacklist: [],
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        }),
      });
    } else if (method === 'PUT') {
      const body = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: groupId,
            group_type: body?.group_type || 'general',
            linked_channel_id: body?.linked_channel_id || null,
            sandbox_enabled: body?.sandbox_enabled ?? false,
            sandbox_duration_hours: body?.sandbox_duration_hours ?? 24,
            admin_notifications: body?.admin_notifications ?? true,
            sensitivity: body?.sensitivity ?? 5,
            admin_alert_chat_id: body?.admin_alert_chat_id || null,
            custom_whitelist: [],
            custom_blacklist: [],
            created_at: '2024-01-01T00:00:00Z',
            updated_at: new Date().toISOString(),
          },
        }),
      });
    } else {
      await route.continue();
    }
  });

  // Mock group stats endpoint
  await page.route(`**/api/groups/${groupId}/stats*`, async (route) => {
    const url = new URL(route.request().url());
    const periodDays = parseInt(url.searchParams.get('period_days') || '7', 10);

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          group_id: groupId,
          period_days: periodDays,
          total_messages: 1000,
          allowed: 900,
          watched: 50,
          limited: 30,
          reviewed: 15,
          blocked: 5,
          fp_count: 2,
          fp_rate: 0.02,
          group_type: 'general',
          top_threat_types: [
            { type: 'SPAM', count: 20 },
            { type: 'SCAM', count: 10 },
            { type: 'CRYPTO_SCAM', count: 5 },
          ],
        },
      }),
    });
  });

  // Mock reviews endpoint
  await page.route(`**/api/groups/${groupId}/reviews`, async (route) => {
    const method = route.request().method();

    if (method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: [
            {
              id: 'review-1',
              group_id: groupId,
              user_id: 111222333,
              username: 'suspected_spammer',
              message_preview: 'Buy crypto now! Limited time offer for amazing returns...',
              risk_score: 85,
              verdict: 'REVIEW',
              threat_types: ['SCAM', 'CRYPTO_SCAM'],
              created_at: new Date(Date.now() - 300000).toISOString(), // 5 mins ago
              message_id: 1001,
            },
            {
              id: 'review-2',
              group_id: groupId,
              user_id: 444555666,
              username: null,
              message_preview: 'Check out this amazing deal at discount-store.example.com...',
              risk_score: 78,
              verdict: 'REVIEW',
              threat_types: ['SPAM'],
              created_at: new Date(Date.now() - 1800000).toISOString(), // 30 mins ago
              message_id: 1002,
            },
            {
              id: 'review-3',
              group_id: groupId,
              user_id: 777888999,
              username: 'new_user_2024',
              message_preview: 'Join our Telegram channel for free signals and profits!',
              risk_score: 92,
              verdict: 'REVIEW',
              threat_types: ['CRYPTO_SCAM', 'PHISHING'],
              created_at: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
              message_id: 1003,
            },
          ],
        }),
      });
    } else if (method === 'POST') {
      const body = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            success: true,
            review_id: body?.review_id,
            action: body?.action,
          },
        }),
      });
    } else {
      await route.continue();
    }
  });

  // Mock channel validation endpoint
  await page.route('**/api/channels/validate*', async (route) => {
    const url = new URL(route.request().url());
    const channel = url.searchParams.get('channel');

    if (channel === 'invalid' || channel === '@invalid_channel') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          error: {
            code: 'CHANNEL_NOT_FOUND',
            message: 'Channel not found or bot is not admin',
          },
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            valid: true,
            channel_id: -1001111111111,
            title: 'Test Channel',
          },
        }),
      });
    }
  });
}

/**
 * Helper to trigger Telegram confirm dialog response
 */
export async function confirmTelegramDialog(page: Page, accept: boolean = true): Promise<void> {
  await page.evaluate((shouldAccept) => {
    const helpers = (window as unknown as Record<string, unknown>).__telegramTestHelpers as {
      confirmDialog: (accept: boolean) => void;
    };
    if (helpers?.confirmDialog) {
      helpers.confirmDialog(shouldAccept);
    }
  }, accept);
}

/**
 * Helper to dismiss Telegram alert dialog
 */
export async function dismissTelegramAlert(page: Page): Promise<void> {
  await page.evaluate(() => {
    const helpers = (window as unknown as Record<string, unknown>).__telegramTestHelpers as {
      dismissAlert: () => void;
    };
    if (helpers?.dismissAlert) {
      helpers.dismissAlert();
    }
  });
}
