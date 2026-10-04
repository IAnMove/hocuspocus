import { defineConfig } from '@playwright/test'
import base from './playwright.config'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const apiPort = process.env.HOCUS_PRODUCTION_TEST_API_PORT || '41981'
const uiPort = process.env.HOCUSPOCUS_E2E_PORT || '41883'
const apiURL = `http://127.0.0.1:${apiPort}`
const uiURL = `http://127.0.0.1:${uiPort}`
const uiRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = process.env.HOCUS_PRODUCTION_TEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
const quotedPython = process.platform === 'win32' ? `"${python.replaceAll('"', '""')}"` : `'${python.replaceAll("'", "'\\''")}'`
process.env.HOCUS_PRODUCTION_TEST_API_URL = apiURL

export default defineConfig({
  ...base,
  testMatch: 'production-journey.spec.ts',
  workers: 1,
  use: { ...base.use, baseURL: uiURL },
  webServer: [
    { command: `npm run build && npx vite preview --host 127.0.0.1 --port ${uiPort} --strictPort`, url: uiURL, cwd: uiRoot,
      env: { HOCUSPOCUS_API_TARGET: apiURL },
      reuseExistingServer: false, timeout: 360_000 },
    { command: `${quotedPython} e2e/helpers/productionApiServer.py --port ${apiPort}`, url: `${apiURL}/test/state`, cwd: uiRoot,
      reuseExistingServer: false, timeout: 30_000 },
  ],
})
