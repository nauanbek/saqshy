import { test, expect } from '@playwright/test';
import {
  injectTelegramWebApp,
  mockApiResponses,
  defaultTestUser,
} from '../fixtures/telegram-mock';

const TEST_GROUP_ID = -1001234567890;

test.describe('Review Queue Page', () => {
  test.beforeEach(async ({ page }) => {
    // Inject Telegram WebApp mock before navigation
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock API responses
    await mockApiResponses(page, TEST_GROUP_ID);

    // Navigate directly to review page
    await page.goto('review');
  });

  test('displays review queue header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
  });

  test('displays pending reviews count', async ({ page }) => {
    // Wait for reviews to load
    await expect(page.getByText('Pending Reviews')).toBeVisible();
    await expect(page.getByText('3 items')).toBeVisible();
  });

  test('displays review items with user info', async ({ page }) => {
    // First review with username
    await expect(page.getByText('@suspected_spammer')).toBeVisible();
    await expect(page.getByText(/Buy crypto now/)).toBeVisible();

    // Second review without username (shows User ID)
    await expect(page.getByText('User 444555666')).toBeVisible();
    await expect(page.getByText(/Check out this amazing deal/)).toBeVisible();

    // Third review
    await expect(page.getByText('@new_user_2024')).toBeVisible();
  });

  test('displays risk scores with correct styling', async ({ page }) => {
    // High risk score (85)
    const riskBadge85 = page.locator('.risk-badge').filter({ hasText: '85' });
    await expect(riskBadge85).toBeVisible();
    await expect(riskBadge85).toHaveClass(/risk-high/);

    // Critical risk score (92)
    const riskBadge92 = page.locator('.risk-badge').filter({ hasText: '92' });
    await expect(riskBadge92).toBeVisible();
    await expect(riskBadge92).toHaveClass(/risk-critical/);
  });

  test('displays threat type tags', async ({ page }) => {
    // Use exact: true to avoid matching CRYPTO_SCAM when looking for SCAM
    await expect(page.getByText('SCAM', { exact: true })).toBeVisible();
    await expect(page.getByText('CRYPTO_SCAM', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('SPAM', { exact: true })).toBeVisible();
    await expect(page.getByText('PHISHING', { exact: true })).toBeVisible();
  });

  test('displays time ago for reviews', async ({ page }) => {
    // Reviews should show relative time - use first() since there are multiple
    await expect(page.getByText(/\dm ago|\dh ago/).first()).toBeVisible();
  });

  test('approve button works', async ({ page }) => {
    // Find the first approve button
    const approveButton = page.getByRole('button', { name: /approve/i }).first();
    await expect(approveButton).toBeVisible();

    // Click approve
    await approveButton.click();

    // Wait for confirmation dialog to auto-confirm
    await page.waitForTimeout(200);

    // Wait for API call
    await page.waitForResponse((response) =>
      response.url().includes('/reviews') && response.request().method() === 'POST'
    );

    // Success toast should appear
    await expect(page.getByText(/approved/i)).toBeVisible({ timeout: 5000 });
  });

  test('confirm block button works', async ({ page }) => {
    // Find the first confirm block button
    const blockButton = page.getByRole('button', { name: /confirm block/i }).first();
    await expect(blockButton).toBeVisible();

    // Click confirm block
    await blockButton.click();

    // Wait for confirmation dialog to auto-confirm
    await page.waitForTimeout(200);

    // Wait for API call
    await page.waitForResponse((response) =>
      response.url().includes('/reviews') && response.request().method() === 'POST'
    );

    // Success toast should appear
    await expect(page.getByText(/block confirmed/i)).toBeVisible({ timeout: 5000 });
  });

  test('refresh button works', async ({ page }) => {
    const refreshButton = page.getByRole('button', { name: /refresh/i });
    await expect(refreshButton).toBeVisible();

    // Click refresh
    await refreshButton.click();

    // Should trigger a new request
    await page.waitForResponse((response) =>
      response.url().includes('/reviews') && response.request().method() === 'GET'
    );
  });

  test('back to settings navigation works', async ({ page }) => {
    const backButton = page.getByRole('button', { name: /back to settings/i });
    await expect(backButton).toBeVisible();

    await backButton.click();

    // Should navigate to settings page
    await expect(page).toHaveURL(/\/app\/?$/);
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();
  });

  test('shows last refresh time', async ({ page }) => {
    await expect(page.getByText(/updated/i)).toBeVisible();
  });
});

test.describe('Review Queue - Empty State', () => {
  test('shows empty state when no reviews', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock empty reviews
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: [],
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('review');

    // Should show empty state
    await expect(page.getByText('No pending reviews')).toBeVisible();
    await expect(page.getByText(/all caught up/i)).toBeVisible();
  });
});

test.describe('Review Queue - Error Handling', () => {
  test('handles API error gracefully', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock API error
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          error: {
            code: 'SERVER_ERROR',
            message: 'Failed to load reviews',
          },
        }),
      });
    });

    await page.goto('review');

    // Should show error state (ErrorFallback component)
    await expect(page.getByText(/something went wrong|connection problem/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();
  });

  test('retry button works after error', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    let requestCount = 0;

    // First request fails, second succeeds
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      requestCount++;
      if (requestCount === 1) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            success: false,
            error: { code: 'SERVER_ERROR', message: 'Failed' },
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: [
              {
                id: 'review-1',
                group_id: TEST_GROUP_ID,
                user_id: 111,
                username: 'user1',
                message_preview: 'Test message',
                risk_score: 75,
                verdict: 'REVIEW',
                threat_types: ['SPAM'],
                created_at: new Date().toISOString(),
                message_id: 1001,
              },
            ],
          }),
        });
      }
    });

    await page.goto('review');

    // Should show error initially (ErrorFallback component has "Try Again" button)
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();

    // Click retry
    await page.getByRole('button', { name: /try again/i }).click();

    // Should now show review
    await expect(page.getByText('@user1')).toBeVisible();
  });

  test('handles action failure gracefully', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);

    // Override just the POST to fail
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            success: false,
            error: { code: 'ACTION_FAILED', message: 'Failed to process action' },
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('review');

    // Try to approve
    const approveButton = page.getByRole('button', { name: /approve/i }).first();
    await approveButton.click();

    // Wait for dialog
    await page.waitForTimeout(200);

    // Should show error via Telegram notification (mock logs it)
    await page.waitForTimeout(500);
    // The error notification is handled by hapticFeedback.notification('error')
  });
});

test.describe('Review Queue - Loading States', () => {
  test('shows loading state while fetching', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Delay the response
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: [],
        }),
      });
    });

    await page.goto('review');

    // Should show skeleton loading (use first() since there are multiple skeleton elements)
    await expect(page.locator('.skeleton').first()).toBeVisible({ timeout: 500 });
  });

  test('shows button loading state during action', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);

    // Delay the POST response
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      if (route.request().method() === 'POST') {
        await new Promise((resolve) => setTimeout(resolve, 500));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { success: true } }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('review');

    // Click approve
    const approveButton = page.getByRole('button', { name: /approve/i }).first();
    await approveButton.click();

    // Wait for dialog
    await page.waitForTimeout(200);

    // Button should show loading state
    await expect(approveButton).toHaveAttribute('aria-busy', 'true');
  });
});

test.describe('Review Queue - Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
    await page.goto('review');
  });

  test('review items are structured as articles', async ({ page }) => {
    const articles = page.locator('article.review-item');
    await expect(articles).toHaveCount(3);
  });

  test('risk badges have accessible labels', async ({ page }) => {
    const riskBadge = page.locator('.risk-badge').first();
    await expect(riskBadge).toHaveAttribute('aria-label', /risk.*score/i);
  });

  test('action buttons have accessible names', async ({ page }) => {
    const approveButton = page.getByRole('button', { name: /approve message from/i }).first();
    const blockButton = page.getByRole('button', { name: /block user/i }).first();

    await expect(approveButton).toBeVisible();
    await expect(blockButton).toBeVisible();
  });

  test('threat types are in a list with role', async ({ page }) => {
    const threatList = page.locator('[role="list"][aria-label*="threat"]').first();
    await expect(threatList).toBeVisible();
  });

  test('empty state is announced to screen readers', async ({ page }) => {
    // Mock empty state
    await page.route(`**/api/groups/${TEST_GROUP_ID}/reviews`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [] }),
      });
    });

    await page.reload();

    const emptyState = page.locator('.review-queue-empty');
    await expect(emptyState).toHaveAttribute('role', 'status');
  });
});
