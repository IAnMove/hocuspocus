import { fileURLToPath } from 'node:url'

/** Absolute path to the classic script Playwright injects before navigation. */
export const bootWatchdogPlaceholderPath = fileURLToPath(
  new URL('./bootWatchdogPlaceholder.js', import.meta.url),
)
