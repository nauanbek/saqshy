import { test, expect } from '@playwright/test';
import {
  injectTelegramWebApp,
  mockApiResponses,
  defaultTestUser,
} from '../fixtures/telegram-mock';

const TEST_GROUP_ID = -1001234567890;

test.describe('Stats Page', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
    await page.goto('stats');
  });

  test('displays statistics header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Statistics' })).toBeVisible();
  });

  test('displays period selector with default 7 days', async ({ page }) => {
    const periodSelector = page.locator('.period-selector');
    await expect(periodSelector).toBeVisible();

    // 7 days should be active by default
    const sevenDayButton = page.getByRole('button', { name: '7 days' });
    await expect(sevenDayButton).toHaveClass(/active/);
  });

  test('displays all period options', async ({ page }) => {
    await expect(page.getByRole('button', { name: '7 days' })).toBeVisible();
    await expect(page.getByRole('button', { name: '14 days' })).toBeVisible();
    await expect(page.getByRole('button', { name: '30 days' })).toBeVisible();
  });

  test('changes period and fetches new data', async ({ page }) => {
    // Click 14 days
    const fourteenDayButton = page.getByRole('button', { name: '14 days' });
    await fourteenDayButton.click();

    // Wait for API call with new period
    const response = await page.waitForResponse((response) =>
      response.url().includes('period_days=14')
    );
    expect(response.status()).toBe(200);

    // Button should now be active
    await expect(fourteenDayButton).toHaveClass(/active/);
  });

  test('displays total messages count', async ({ page }) => {
    await expect(page.getByText('Total Messages')).toBeVisible();
    await expect(page.getByText('1,000')).toBeVisible();
  });

  test('displays all verdict categories', async ({ page }) => {
    // Check verdict labels are visible (use stat-label class for specificity)
    const statsCard = page.locator('.stats-card');
    await expect(statsCard.getByText('Allowed')).toBeVisible();
    await expect(statsCard.getByText('Watched')).toBeVisible();
    await expect(statsCard.getByText('Limited')).toBeVisible();
    await expect(statsCard.getByText('Reviewed')).toBeVisible();
    await expect(statsCard.getByText('Blocked')).toBeVisible();

    // Check that stat values are displayed (using exact text match)
    const verdictGrid = page.locator('.verdict-grid');
    await expect(verdictGrid.getByText('900', { exact: true })).toBeVisible();
    await expect(verdictGrid.getByText('50', { exact: true })).toBeVisible();
    await expect(verdictGrid.getByText('30', { exact: true })).toBeVisible();
    await expect(verdictGrid.getByText('15', { exact: true })).toBeVisible();
    await expect(verdictGrid.getByText('5', { exact: true })).toBeVisible();
  });

  test('displays top threat types', async ({ page }) => {
    await expect(page.getByText('Top Threat Types')).toBeVisible();
    // Use exact: true to avoid matching CRYPTO_SCAM when looking for SCAM
    await expect(page.getByText('SPAM', { exact: true })).toBeVisible();
    await expect(page.getByText('SCAM', { exact: true })).toBeVisible();
    await expect(page.getByText('CRYPTO_SCAM', { exact: true })).toBeVisible();
  });

  test('back to settings navigation works', async ({ page }) => {
    const backButton = page.getByRole('button', { name: /back to settings/i });
    await expect(backButton).toBeVisible();

    await backButton.click();

    // Should navigate to settings page
    await expect(page).toHaveURL(/\/app\/?$/);
  });

  test('review queue navigation works', async ({ page }) => {
    const reviewButton = page.getByRole('button', { name: /review queue/i });
    await expect(reviewButton).toBeVisible();

    await reviewButton.click();

    // Should navigate to review page
    await expect(page).toHaveURL(/\/review$/);
  });

  test('displays period in stats header', async ({ page }) => {
    await expect(page.getByText('Last 7 days')).toBeVisible();
  });
});

test.describe('Stats Page - False Positive Rate (Deals Groups)', () => {
  test('displays FP rate card for deals group type', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock deals group stats
    await page.route(`**/api/groups/${TEST_GROUP_ID}/stats*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: TEST_GROUP_ID,
            period_days: 7,
            total_messages: 1000,
            allowed: 850,
            watched: 60,
            limited: 40,
            reviewed: 30,
            blocked: 20,
            fp_count: 1,
            fp_rate: 0.02, // 2% - within target
            group_type: 'deals',
            top_threat_types: [{ type: 'SPAM', count: 30 }],
          },
        }),
      });
    });

    await page.goto('stats');

    // FP rate card should be visible
    await expect(page.getByText('False Positive Rate')).toBeVisible();
    await expect(page.getByText('2.0%')).toBeVisible();
    await expect(page.getByText(/admin overrides/)).toBeVisible();
    await expect(page.getByText(/FP rate is within target/)).toBeVisible();
  });

  test('shows warning for high FP rate', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock deals group with high FP rate
    await page.route(`**/api/groups/${TEST_GROUP_ID}/stats*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: TEST_GROUP_ID,
            period_days: 7,
            total_messages: 1000,
            allowed: 800,
            watched: 80,
            limited: 50,
            reviewed: 40,
            blocked: 30,
            fp_count: 5,
            fp_rate: 0.15, // 15% - high FP rate
            group_type: 'deals',
            top_threat_types: [{ type: 'SPAM', count: 50 }],
          },
        }),
      });
    });

    await page.goto('stats');

    // Should show warning
    await expect(page.getByText('False Positive Rate')).toBeVisible();
    await expect(page.getByText('15.0%')).toBeVisible();
    await expect(page.getByText(/High FP rate/)).toBeVisible();
    await expect(page.getByText(/adjusting sensitivity/i)).toBeVisible();
  });

  test('does not show FP rate card for non-deals groups', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID); // Default is 'general' group type

    await page.goto('stats');

    // FP rate card should NOT be visible for general groups
    await expect(page.getByText('False Positive Rate')).not.toBeVisible();
  });
});

test.describe('Stats Page - Loading States', () => {
  test('shows loading skeleton while fetching', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Delay the response
    await page.route(`**/api/groups/${TEST_GROUP_ID}/stats*`, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: TEST_GROUP_ID,
            period_days: 7,
            total_messages: 1000,
            allowed: 900,
            watched: 50,
            limited: 30,
            reviewed: 15,
            blocked: 5,
            fp_count: 2,
            fp_rate: 0.02,
            group_type: 'general',
            top_threat_types: [],
          },
        }),
      });
    });

    await page.goto('stats');

    // Should show skeleton (use first() since there are multiple skeleton elements)
    await expect(page.locator('.skeleton').first()).toBeVisible({ timeout: 500 });
  });
});

test.describe('Stats Page - Error Handling', () => {
  test('shows error state when stats fail to load', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    await page.route(`**/api/groups/${TEST_GROUP_ID}/stats*`, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          error: { code: 'SERVER_ERROR', message: 'Failed to load stats' },
        }),
      });
    });

    await page.goto('stats');

    // ErrorFallback shows "Something Went Wrong" or "Connection Problem" as title
    await expect(page.getByText(/something went wrong|connection problem/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();
  });

  test('retry button works', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    let requestCount = 0;
    await page.route(`**/api/groups/${TEST_GROUP_ID}/stats*`, async (route) => {
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
            data: {
              group_id: TEST_GROUP_ID,
              period_days: 7,
              total_messages: 500,
              allowed: 450,
              watched: 25,
              limited: 15,
              reviewed: 7,
              blocked: 3,
              fp_count: 0,
              fp_rate: 0,
              group_type: 'general',
              top_threat_types: [],
            },
          }),
        });
      }
    });

    await page.goto('stats');

    // Should show error with "Try Again" button
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();

    // Click retry
    await page.getByRole('button', { name: /try again/i }).click();

    // Should now show stats
    await expect(page.getByText('Total Messages')).toBeVisible();
    await expect(page.getByText('500')).toBeVisible();
  });
});

test.describe('Stats Page - Empty State', () => {
  test('handles no threat types gracefully', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    await page.route(`**/api/groups/${TEST_GROUP_ID}/stats*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: TEST_GROUP_ID,
            period_days: 7,
            total_messages: 100,
            allowed: 100,
            watched: 0,
            limited: 0,
            reviewed: 0,
            blocked: 0,
            fp_count: 0,
            fp_rate: 0,
            group_type: 'general',
            top_threat_types: [], // No threats
          },
        }),
      });
    });

    await page.goto('stats');

    // Should show stats but no threat types section
    await expect(page.getByText('Total Messages')).toBeVisible();
    await expect(page.getByText('Top Threat Types')).not.toBeVisible();
  });
});

test.describe('Stats Page - Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
    await page.goto('stats');
  });

  test('stat items have visible labels', async ({ page }) => {
    // Each stat should have a visible label
    await expect(page.getByText('Allowed')).toBeVisible();
    await expect(page.getByText('Watched')).toBeVisible();
    await expect(page.getByText('Limited')).toBeVisible();
    await expect(page.getByText('Reviewed')).toBeVisible();
    await expect(page.getByText('Blocked')).toBeVisible();
  });

  test('period buttons are keyboard accessible', async ({ page }) => {
    // Focus on period selector
    const sevenDayButton = page.getByRole('button', { name: '7 days' });
    await sevenDayButton.focus();

    // Tab to next button
    await page.keyboard.press('Tab');

    // 14 days button should be focused
    const fourteenDayButton = page.getByRole('button', { name: '14 days' });
    await expect(fourteenDayButton).toBeFocused();
  });

  test('stats card has proper structure', async ({ page }) => {
    // Should have a stats card container
    await expect(page.locator('.stats-card')).toBeVisible();

    // Should have proper headings
    await expect(page.getByRole('heading', { name: 'Moderation Stats' })).toBeVisible();
  });
});
