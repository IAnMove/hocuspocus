import { defineConfig } from '@playwright/test'

const baseURL = process.env.HOCUSPOCUS_BASE_URL || 'http://127.0.0.1:7860'

export default defineConfig({
  testDir: './live-specs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30 * 60_000,
  expect: { timeout: 30_000 },
  outputDir: '../test-results/wizard-live',
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: '../playwright-report/wizard-live' }],
    ['json', { outputFile: '../test-results/wizard-live/results.json' }],
  ],
  use: {
    baseURL,
    locale: 'en-US',
    viewport: { width: 1440, height: 900 },
    trace: 'on',
    screenshot: 'on',
    video: 'retain-on-failure',
  },
})
