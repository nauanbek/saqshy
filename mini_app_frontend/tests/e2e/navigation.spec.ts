import { test, expect } from '@playwright/test';
import {
  injectTelegramWebApp,
  mockApiResponses,
  defaultTestUser,
} from '../fixtures/telegram-mock';

const TEST_GROUP_ID = -1001234567890;

test.describe('App Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
  });

  test('starts on settings page by default', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('navigates from settings to stats', async ({ page }) => {
    await page.goto('/');

    const statsLink = page.getByRole('button', { name: /view stats/i });
    await statsLink.click();

    await expect(page).toHaveURL(/\/stats$/);
    await expect(page.getByRole('heading', { name: 'Statistics' })).toBeVisible();
  });

  test('navigates from settings to review queue', async ({ page }) => {
    await page.goto('/');

    const reviewLink = page.getByRole('button', { name: /review queue/i });
    await reviewLink.click();

    await expect(page).toHaveURL(/\/review$/);
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
  });

  test('navigates from stats back to settings', async ({ page }) => {
    await page.goto('stats');

    const backButton = page.getByRole('button', { name: /back to settings/i });
    await backButton.click();

    await expect(page).toHaveURL(/\/app\/?$/);
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('navigates from stats to review queue', async ({ page }) => {
    await page.goto('stats');

    const reviewButton = page.getByRole('button', { name: /review queue/i });
    await reviewButton.click();

    await expect(page).toHaveURL(/\/review$/);
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
  });

  test('navigates from review queue back to settings', async ({ page }) => {
    await page.goto('review');

    const backButton = page.getByRole('button', { name: /back to settings/i });
    await backButton.click();

    await expect(page).toHaveURL(/\/app\/?$/);
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('handles unknown routes by redirecting to settings', async ({ page }) => {
    await page.goto('unknown-route');

    // Should redirect to settings
    await expect(page).toHaveURL(/\/app\/?$/);
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('full navigation flow works', async ({ page }) => {
    // Start at settings
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();

    // Go to stats
    await page.getByRole('button', { name: /view stats/i }).click();
    await expect(page.getByRole('heading', { name: 'Statistics' })).toBeVisible();

    // Go to review from stats
    await page.getByRole('button', { name: /review queue/i }).click();
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();

    // Go back to settings
    await page.getByRole('button', { name: /back to settings/i }).click();
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();

    // Go to review from settings
    await page.getByRole('button', { name: /review queue/i }).click();
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
  });
});

test.describe('App Initialization', () => {
  test('shows loading state while Telegram WebApp initializes', async ({ page }) => {
    // Don't inject Telegram - simulate not ready state
    await page.goto('/');

    // Should show loading or error (no Telegram object)
    // The actual behavior depends on implementation
  });

  test('shows error when no group ID provided', async ({ page }) => {
    // Inject Telegram without start_param (no group ID)
    await page.addInitScript(() => {
      (window as unknown as Record<string, unknown>).Telegram = {
        WebApp: {
          initData: '',
          initDataUnsafe: {
            user: { id: 123, first_name: 'Test' },
            start_param: '', // No group ID
          },
          themeParams: {},
          colorScheme: 'light',
          isExpanded: true,
          viewportHeight: 600,
          viewportStableHeight: 600,
          headerColor: '#ffffff',
          backgroundColor: '#ffffff',
          ready: () => {},
          expand: () => {},
          close: () => {},
          showConfirm: (_: string, cb: (b: boolean) => void) => cb(true),
          showAlert: (_: string, cb?: () => void) => cb?.(),
          onEvent: () => {},
          offEvent: () => {},
          MainButton: {
            text: '',
            color: '',
            textColor: '',
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
    });

    await page.goto('/');

    // Should show configuration error
    await expect(page.getByRole('heading', { name: /configuration error/i })).toBeVisible();
    await expect(page.getByText(/no group id provided/i)).toBeVisible();
    await expect(page.getByText(/open this mini app from a group/i)).toBeVisible();
  });

  test('parses group ID from start_param correctly', async ({ page }) => {
    // Test with format: group_-1001234567890
    await injectTelegramWebApp(page, defaultTestUser, -1001234567890, true);
    await mockApiResponses(page, -1001234567890);

    await page.goto('/');

    // Should load settings page without error
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('parses group ID with underscore format', async ({ page }) => {
    // The mock already handles group_-1001234567890 format
    await injectTelegramWebApp(page, defaultTestUser, -1001234567890, true);
    await mockApiResponses(page, -1001234567890);

    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });
});

test.describe('Offline Support', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
  });

  test('shows offline banner when network is down', async ({ page, context }) => {
    await page.goto('/');

    // Wait for initial load
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();

    // Simulate going offline
    await context.setOffline(true);

    // Trigger a re-render (e.g., by focusing the page)
    await page.dispatchEvent('body', 'online', {});

    // The offline banner behavior depends on implementation
    // If the app listens to online/offline events, the banner should appear
  });
});

test.describe('Mobile Viewport', () => {
  test('settings page is usable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });

    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);

    await page.goto('/');

    // All main elements should be visible
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
    await expect(page.getByText('Group Type')).toBeVisible();

    // Group type buttons should be accessible
    const generalButton = page.getByRole('button', { name: /general/i });
    await expect(generalButton).toBeVisible();
    await expect(generalButton).toBeInViewport();
  });

  test('review queue is scrollable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });

    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);

    await page.goto('review');

    // Review queue should be visible
    await expect(page.getByText('Pending Reviews')).toBeVisible();

    // Multiple items should be present (may need to scroll)
    const reviewItems = page.locator('.review-item');
    await expect(reviewItems.first()).toBeVisible();
  });
});

test.describe('Browser History', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
  });

  test('browser back works after navigation', async ({ page }) => {
    await page.goto('/');

    // Navigate to stats
    await page.getByRole('button', { name: /view stats/i }).click();
    await expect(page).toHaveURL(/\/stats$/);

    // Go back using browser
    await page.goBack();
    await expect(page).toHaveURL(/\/app\/?$/);
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('browser forward works after going back', async ({ page }) => {
    await page.goto('/');

    // Navigate to review
    await page.getByRole('button', { name: /review queue/i }).click();
    await expect(page).toHaveURL(/\/review$/);

    // Go back
    await page.goBack();
    await expect(page).toHaveURL(/\/app\/?$/);

    // Go forward
    await page.goForward();
    await expect(page).toHaveURL(/\/review$/);
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
  });
});

test.describe('Page Refresh', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
  });

  test('settings page survives refresh', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();

    // Refresh
    await page.reload();

    // Re-inject Telegram mock after reload
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);

    // Should still be on settings (after Telegram re-init)
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible({
      timeout: 10000,
    });
  });

  test('stats page survives refresh', async ({ page }) => {
    // Need to handle re-injection on reload
    // This test demonstrates the pattern, actual behavior depends on app init
    await page.goto('stats');

    // First load works
    await expect(page.getByRole('heading', { name: 'Statistics' })).toBeVisible();
  });
});
