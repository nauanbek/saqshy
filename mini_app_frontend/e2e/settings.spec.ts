import { test, expect, mockTelegramWebApp } from './fixtures/telegram';

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    // Mock Telegram WebApp and API responses
    // Telegram group IDs are negative for supergroups
    await mockTelegramWebApp(page, { groupId: -1001234567890 });

    // Mock API endpoints
    await page.route('**/api/groups/*/settings', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: {
              group_id: -1001234567890,
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
      } else if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: {
              group_id: -1001234567890,
              ...body,
              updated_at: new Date().toISOString(),
            },
          }),
        });
      }
    });
  });

  test('should load settings page', async ({ page }) => {
    await page.goto('/app/?group_id=-1001234567890');

    // Wait for loading to complete
    await expect(page.locator('h1')).toContainText('Group Settings');

    // Check that group type selector is visible (use role selector for button labels)
    await expect(page.locator('.type-option-label').filter({ hasText: 'General' })).toBeVisible();
    await expect(page.locator('.type-option-label').filter({ hasText: 'Tech' })).toBeVisible();
    await expect(page.locator('.type-option-label').filter({ hasText: 'Deals' })).toBeVisible();
    await expect(page.locator('.type-option-label').filter({ hasText: 'Crypto' })).toBeVisible();
  });

  test('should navigate to stats page', async ({ page }) => {
    await page.goto('/app/?group_id=-1001234567890');

    // Wait for page to load
    await expect(page.locator('h1')).toContainText('Group Settings');

    // Click on stats link
    await page.getByText('View Stats').click();

    // Should navigate to stats page
    await expect(page).toHaveURL(/\/app\/stats/);
  });

  test('should navigate to review queue', async ({ page }) => {
    await page.goto('/app/?group_id=-1001234567890');

    // Wait for page to load
    await expect(page.locator('h1')).toContainText('Group Settings');

    // Click on review queue link
    await page.getByText('Review Queue').click();

    // Should navigate to review page
    await expect(page).toHaveURL(/\/app\/review/);
  });

  test('should change group type', async ({ page }) => {
    await page.goto('/app/?group_id=-1001234567890');

    // Wait for page to load
    await expect(page.locator('h1')).toContainText('Group Settings');

    // Click on Tech type
    await page.getByText('Tech').first().click();

    // Should show confirmation or selected state
    await expect(page.getByText('Tech')).toBeVisible();
  });

  test('should show skeleton loader while loading', async ({ page }) => {
    // Delay API response
    await page.route('**/api/groups/*/settings', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: -1001234567890,
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

    await page.goto('/app/?group_id=-1001234567890');

    // Should show skeleton
    await expect(page.locator('.skeleton').first()).toBeVisible();

    // Wait for content to load
    await expect(page.getByText('General')).toBeVisible({ timeout: 5000 });
  });
});
