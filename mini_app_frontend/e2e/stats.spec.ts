import { test, expect, mockTelegramWebApp } from './fixtures/telegram';

test.describe('Stats Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockTelegramWebApp(page, { groupId: 123 });

    // Mock stats API
    await page.route('**/api/groups/*/stats*', async (route) => {
      const url = new URL(route.request().url());
      const periodDays = url.searchParams.get('period_days') || '7';

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: 123,
            period_days: parseInt(periodDays),
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
            ],
          },
        }),
      });
    });

    // Mock settings for navigation
    await page.route('**/api/groups/*/settings', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: 123,
            group_type: 'general',
            linked_channel_id: null,
            sandbox_enabled: false,
            sandbox_duration_hours: 24,
            admin_notifications: true,
            custom_whitelist: [],
            custom_blacklist: [],
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        }),
      });
    });
  });

  test('should load stats page', async ({ page }) => {
    await page.goto('/app/stats?group_id=123');

    await expect(page.locator('h1')).toContainText('Statistics');

    // Check that stats are displayed (formatted with comma)
    await expect(page.getByText('1,000')).toBeVisible();
  });

  test('should change period', async ({ page }) => {
    await page.goto('/app/stats?group_id=123');

    await expect(page.locator('h1')).toContainText('Statistics');

    // Click on 30 days
    await page.getByText('30 days').click();

    // Period button should have active styling
    const periodButton = page.getByRole('button', { name: '30 days' });
    await expect(periodButton).toBeVisible();
    // Verify button was clicked by checking the URL or stats period change
    await expect(page.locator('.stats-period')).toContainText('30 days');
  });

  test('should show verdict breakdown', async ({ page }) => {
    await page.goto('/app/stats?group_id=123');

    // Wait for stats to load (formatted with comma)
    await expect(page.getByText('1,000')).toBeVisible();

    // Check verdict labels are present
    await expect(page.getByText('Allowed')).toBeVisible();
    await expect(page.getByText('Blocked')).toBeVisible();
  });

  test('should navigate back to settings', async ({ page }) => {
    await page.goto('/app/stats?group_id=123');

    await expect(page.locator('h1')).toContainText('Statistics');

    // Click back button
    await page.getByText('Back to Settings').click();

    // Should navigate to settings
    await expect(page).toHaveURL(/\/app\/?(\?|$)/);
  });
});
