import { defineConfig } from '@playwright/test'

// The screen-effect specs launch their own Chromium and need no app server: this config runs them without the build and
// preview server of `playwright.config.ts` (`npm run test:e2e:fx`).
export default defineConfig({
  testDir: './specs',
  testMatch: /scene-fx-.*\.spec\.ts/,
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 300_000,
  reporter: 'list',
  outputDir: '../test-results',
})
