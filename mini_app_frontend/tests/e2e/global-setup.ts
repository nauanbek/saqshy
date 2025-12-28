import { chromium, FullConfig } from '@playwright/test';

/**
 * Global setup runs once before all tests.
 * Use this for any one-time setup like ensuring browsers are installed.
 */
async function globalSetup(config: FullConfig): Promise<void> {
  console.log('Running global setup for E2E tests...');

  // Optionally verify browser can launch
  try {
    const browser = await chromium.launch();
    await browser.close();
    console.log('Browser launch verification successful');
  } catch (error) {
    console.error('Browser launch failed. Run: npx playwright install');
    throw error;
  }
}

export default globalSetup;
