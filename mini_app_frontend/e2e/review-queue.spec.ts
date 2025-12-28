import { test, expect, mockTelegramWebApp } from './fixtures/telegram';

test.describe('Review Queue Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockTelegramWebApp(page, { groupId: 123 });

    // Mock reviews API
    await page.route('**/api/groups/*/reviews', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: [
              {
                id: 'review-1',
                group_id: 123,
                user_id: 111,
                username: 'spammer1',
                message_preview: 'Buy crypto now! Limited time offer...',
                risk_score: 85,
                verdict: 'review',
                threat_types: ['SCAM', 'CRYPTO_SCAM'],
                created_at: new Date().toISOString(),
                message_id: 1001,
              },
              {
                id: 'review-2',
                group_id: 123,
                user_id: 222,
                username: null,
                message_preview: 'Check out this amazing deal...',
                risk_score: 78,
                verdict: 'review',
                threat_types: ['SPAM'],
                created_at: new Date().toISOString(),
                message_id: 1002,
              },
            ],
          }),
        });
      } else if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { success: true },
          }),
        });
      }
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

  test('should load review queue page', async ({ page }) => {
    await page.goto('/app/review?group_id=123');

    await expect(page.locator('h1')).toContainText('Review Queue');

    // Check that reviews are displayed
    await expect(page.getByText('spammer1')).toBeVisible();
    await expect(page.getByText('Buy crypto now!')).toBeVisible();
  });

  test('should show review items with risk score', async ({ page }) => {
    await page.goto('/app/review?group_id=123');

    await expect(page.locator('h1')).toContainText('Review Queue');

    // Check risk scores are displayed (score 85 should be high/critical)
    await expect(page.getByText('85')).toBeVisible();
    await expect(page.getByText('78')).toBeVisible();
  });

  test('should show threat tags', async ({ page }) => {
    await page.goto('/app/review?group_id=123');

    // Wait for content
    await expect(page.getByText('spammer1')).toBeVisible();

    // Check threat tags (use exact match)
    await expect(page.getByText('SCAM', { exact: true })).toBeVisible();
    await expect(page.getByText('SPAM', { exact: true })).toBeVisible();
  });

  test('should have approve button', async ({ page }) => {
    await page.goto('/app/review?group_id=123');

    await expect(page.getByText('spammer1')).toBeVisible();

    // Check approve button exists
    const approveButtons = page.getByRole('button', { name: /approve/i });
    await expect(approveButtons.first()).toBeVisible();
  });

  test('should show empty state when no reviews', async ({ page }) => {
    // Override with empty reviews
    await page.route('**/api/groups/*/reviews', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: [],
        }),
      });
    });

    await page.goto('/app/review?group_id=123');

    await expect(page.locator('h1')).toContainText('Review Queue');

    // Should show empty state
    await expect(page.getByText(/no pending reviews/i)).toBeVisible();
  });

  test('should navigate back to settings', async ({ page }) => {
    await page.goto('/app/review?group_id=123');

    await expect(page.locator('h1')).toContainText('Review Queue');

    // Click back button
    await page.getByText('Back to Settings').click();

    // Should navigate to settings
    await expect(page).toHaveURL(/\/app\/?(\?|$)/);
  });
});
