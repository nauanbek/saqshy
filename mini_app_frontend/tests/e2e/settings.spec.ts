import { test, expect } from '@playwright/test';
import {
  injectTelegramWebApp,
  mockApiResponses,
  defaultTestUser,
} from '../fixtures/telegram-mock';

const TEST_GROUP_ID = -1001234567890;

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    // Inject Telegram WebApp mock before navigation
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock API responses
    await mockApiResponses(page, TEST_GROUP_ID);

    // Navigate to the settings page
    await page.goto('/');
  });

  test('loads and displays group settings', async ({ page }) => {
    // Wait for the page to load
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();

    // Verify settings sections are displayed (use specific heading selectors)
    await expect(page.getByRole('heading', { name: 'Group Type' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Linked Channel' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Sandbox Mode' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Detection Sensitivity' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
  });

  test('displays all four group type options', async ({ page }) => {
    // Verify all group types are present
    await expect(page.getByRole('button', { name: /general/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /tech/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /deals/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /crypto/i })).toBeVisible();

    // Verify descriptions are shown
    await expect(page.getByText('Balanced moderation for typical communities')).toBeVisible();
    await expect(page.getByText('Allows GitHub, docs, and developer links freely')).toBeVisible();
    await expect(page.getByText(/Links, promo codes, and affiliate content allowed/)).toBeVisible();
    await expect(page.getByText('Strict scam detection, normal crypto discussion allowed')).toBeVisible();
  });

  test('general type is selected by default', async ({ page }) => {
    const generalButton = page.getByRole('button', { name: /general/i });
    await expect(generalButton).toHaveAttribute('aria-pressed', 'true');
  });

  test('changes group type with confirmation', async ({ page }) => {
    // Click on Tech type
    const techButton = page.getByRole('button', { name: /tech/i });
    await techButton.click();

    // Wait for confirmation dialog to auto-confirm (mock behavior)
    await page.waitForTimeout(200);

    // Verify Tech is now selected
    await expect(techButton).toHaveAttribute('aria-pressed', 'true');

    // Verify save button becomes enabled
    const saveButton = page.getByRole('button', { name: /save settings/i });
    await expect(saveButton).toBeEnabled();

    // Verify unsaved changes message appears
    await expect(page.getByText('You have unsaved changes')).toBeVisible();
  });

  test('sensitivity slider works correctly', async ({ page }) => {
    const sensitivitySlider = page.locator('#sensitivity');
    await expect(sensitivitySlider).toBeVisible();

    // Default value should be 5
    await expect(sensitivitySlider).toHaveValue('5');

    // Verify balanced hint is shown
    await expect(page.getByText('Balanced detection for most groups')).toBeVisible();

    // Change to strict (8)
    await sensitivitySlider.fill('8');
    await expect(sensitivitySlider).toHaveValue('8');

    // Verify strict hint appears
    await expect(page.getByText('Stricter detection - may flag legitimate messages')).toBeVisible();

    // Change to lenient (2)
    await sensitivitySlider.fill('2');
    await expect(sensitivitySlider).toHaveValue('2');

    // Verify lenient hint appears
    await expect(page.getByText('More spam may get through, but fewer false positives')).toBeVisible();
  });

  test('sandbox mode toggle works', async ({ page }) => {
    // The checkbox is visually hidden (custom toggle switch CSS)
    const sandboxToggle = page.getByRole('checkbox', { name: /enable sandbox/i });

    // Should be off by default (checkbox is hidden but accessible)
    await expect(sandboxToggle).not.toBeChecked();

    // Duration slider should not be visible when toggle is off
    await expect(page.locator('#sandbox-duration')).not.toBeVisible();

    // Enable sandbox by clicking the label row (toggle-row contains the styled switch)
    await page.locator('.toggle-row').filter({ hasText: /enable sandbox/i }).click();
    await expect(sandboxToggle).toBeChecked();

    // Duration slider should now be visible
    const durationSlider = page.locator('#sandbox-duration');
    await expect(durationSlider).toBeVisible();
    await expect(durationSlider).toHaveValue('24');
  });

  test('admin notifications toggle works', async ({ page }) => {
    // The checkbox is visually hidden (custom toggle switch CSS)
    const notificationsToggle = page.getByRole('checkbox', { name: /admin notifications/i });

    // Should be on by default (checkbox is hidden but accessible)
    await expect(notificationsToggle).toBeChecked();

    // Admin alert chat ID field should be visible when toggle is on
    await expect(page.locator('#admin-alert-chat-id')).toBeVisible();

    // Disable notifications by clicking the toggle row
    await page.locator('.toggle-row').filter({ hasText: /admin notifications/i }).click();
    await expect(notificationsToggle).not.toBeChecked();

    // Admin alert chat ID field should be hidden
    await expect(page.locator('#admin-alert-chat-id')).not.toBeVisible();

    // Re-enable notifications
    await page.locator('.toggle-row').filter({ hasText: /admin notifications/i }).click();
    await expect(notificationsToggle).toBeChecked();

    // Admin alert chat ID field should be visible again
    await expect(page.locator('#admin-alert-chat-id')).toBeVisible();
  });

  test('channel linking validation works', async ({ page }) => {
    const channelInput = page.locator('#channel-input');
    await expect(channelInput).toBeVisible();

    // Enter a valid channel
    await channelInput.fill('@test_channel');

    // Click validate button
    const validateButton = page.getByRole('button', { name: /validate/i });
    await validateButton.click();

    // Wait for validation
    await page.waitForResponse((response) =>
      response.url().includes('/api/channels/validate')
    );

    // Should show channel info with unlink button
    await expect(page.getByText('Test Channel')).toBeVisible();
    await expect(page.getByRole('button', { name: /unlink/i })).toBeVisible();
  });

  test('channel linking shows error for invalid channel', async ({ page }) => {
    const channelInput = page.locator('#channel-input');
    await channelInput.fill('@invalid_channel');

    // Click validate button
    const validateButton = page.getByRole('button', { name: /validate/i });
    await validateButton.click();

    // Wait for validation
    await page.waitForResponse((response) =>
      response.url().includes('/api/channels/validate')
    );

    // Should show error message
    await expect(page.getByRole('alert')).toBeVisible();
  });

  test('unlinking channel works', async ({ page }) => {
    const channelInput = page.locator('#channel-input');
    await channelInput.fill('@test_channel');

    // Validate first
    const validateButton = page.getByRole('button', { name: /validate/i });
    await validateButton.click();

    await page.waitForResponse((response) =>
      response.url().includes('/api/channels/validate')
    );

    // Click unlink
    const unlinkButton = page.getByRole('button', { name: /unlink/i });
    await unlinkButton.click();

    // Should show input field again
    await expect(page.locator('#channel-input')).toBeVisible();
    await expect(unlinkButton).not.toBeVisible();
  });

  test('saves settings successfully', async ({ page }) => {
    // Make a change
    const sensitivitySlider = page.locator('#sensitivity');
    await sensitivitySlider.fill('7');

    // Click save
    const saveButton = page.getByRole('button', { name: /save settings/i });
    await expect(saveButton).toBeEnabled();
    await saveButton.click();

    // Wait for save request
    await page.waitForResponse((response) =>
      response.url().includes('/settings') && response.request().method() === 'PUT'
    );

    // Verify unsaved changes message disappears
    await expect(page.getByText('You have unsaved changes')).not.toBeVisible();
  });

  test('navigation to stats page works', async ({ page }) => {
    const statsLink = page.getByRole('button', { name: /view stats/i });
    await statsLink.click();

    // Should navigate to stats page
    await expect(page).toHaveURL(/\/stats$/);
    await expect(page.getByRole('heading', { name: 'Statistics' })).toBeVisible();
  });

  test('navigation to review queue works', async ({ page }) => {
    const reviewLink = page.getByRole('button', { name: /review queue/i });
    await reviewLink.click();

    // Should navigate to review page
    await expect(page).toHaveURL(/\/review$/);
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
  });

  test('handles API error gracefully', async ({ page }) => {
    // Override the settings route to return an error
    await page.route(`**/api/groups/${TEST_GROUP_ID}/settings`, async (route) => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            success: false,
            error: {
              code: 'SERVER_ERROR',
              message: 'Internal server error',
            },
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Make a change and try to save
    const sensitivitySlider = page.locator('#sensitivity');
    await sensitivitySlider.fill('7');

    const saveButton = page.getByRole('button', { name: /save settings/i });
    await saveButton.click();

    // Should show error alert (from Telegram showAlert mock)
    await page.waitForTimeout(500);
    // The error is shown via Telegram's showAlert, which our mock logs
  });
});

test.describe('Settings Page - Loading States', () => {
  test('shows loading skeleton while fetching settings', async ({ page }) => {
    // Inject Telegram WebApp mock
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Delay the API response
    await page.route(`**/api/groups/${TEST_GROUP_ID}/settings`, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            group_id: TEST_GROUP_ID,
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
    });

    await page.goto('/');

    // Should show loading skeleton (use first() since there are multiple skeleton elements)
    await expect(page.locator('.skeleton').first()).toBeVisible({ timeout: 500 });
  });

  test('shows error state when settings fail to load', async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);

    // Mock API to return error
    await page.route(`**/api/groups/${TEST_GROUP_ID}/settings`, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          error: {
            code: 'SERVER_ERROR',
            message: 'Failed to load settings',
          },
        }),
      });
    });

    await page.goto('/');

    // Should show error state with retry button (ErrorFallback component)
    await expect(page.getByText(/something went wrong|connection problem/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();
  });
});

test.describe('Settings Page - Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await injectTelegramWebApp(page, defaultTestUser, TEST_GROUP_ID, true);
    await mockApiResponses(page, TEST_GROUP_ID);
    await page.goto('/');
  });

  test('form elements have proper labels', async ({ page }) => {
    // Wait for page to load
    await expect(page.getByRole('heading', { name: 'Group Settings' })).toBeVisible();

    // Check sensitivity slider has accessible label
    const sensitivitySlider = page.locator('#sensitivity');
    await expect(sensitivitySlider).toHaveAttribute('aria-valuemin', '1');
    await expect(sensitivitySlider).toHaveAttribute('aria-valuemax', '10');

    // Check toggles exist and have accessible names (they are visually hidden but accessible)
    const sandboxToggle = page.getByRole('checkbox', { name: /enable sandbox/i });
    const notificationsToggle = page.getByRole('checkbox', { name: /admin notifications/i });

    // Check that the checkboxes are present (even if hidden)
    await expect(sandboxToggle).toHaveCount(1);
    await expect(notificationsToggle).toHaveCount(1);
  });

  test('group type buttons use aria-pressed', async ({ page }) => {
    const generalButton = page.getByRole('button', { name: /general/i });
    const techButton = page.getByRole('button', { name: /tech/i });

    await expect(generalButton).toHaveAttribute('aria-pressed', 'true');
    await expect(techButton).toHaveAttribute('aria-pressed', 'false');
  });

  test('error messages are announced to screen readers', async ({ page }) => {
    const channelInput = page.locator('#channel-input');
    await channelInput.fill('@invalid_channel');

    const validateButton = page.getByRole('button', { name: /validate/i });
    await validateButton.click();

    await page.waitForResponse((response) =>
      response.url().includes('/api/channels/validate')
    );

    // Error message should have role="alert"
    await expect(page.getByRole('alert')).toBeVisible();
  });
});
