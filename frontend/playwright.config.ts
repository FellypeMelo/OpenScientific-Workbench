import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'pnpm run dev',
    url: 'http://localhost:3000',
    // The e2e workflow pre-starts the frontend (`pnpm run start &`) before invoking
    // Playwright, so always reuse an already-listening server instead of trying to
    // spawn a second one on the same port (which fails in CI with "port already used").
    // When nothing is listening (local runs), Playwright still starts `command`.
    reuseExistingServer: true,
  },
})
