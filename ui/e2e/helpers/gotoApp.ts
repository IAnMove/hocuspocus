import { expect, type Page } from '@playwright/test'
import { formatUnhandled, installApiRoutes, type ApiRouteSession } from './apiRoutes'
import { bootWatchdogPlaceholderPath } from './bootWatchdogPlaceholderPath'

export async function gotoApp(page: Page): Promise<ApiRouteSession> {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const session = await installApiRoutes(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
  })
  // index.html replaces the document after 10s if #root has no element
  // children. The production bundle can take longer than that to parse
  // on a cold CI runner; keep a placeholder so the watchdog stays inert.
  // Inject via path: a serialized function picks up the test runner's
  // __name helper, which is not defined in the page.
  await page.addInitScript({ path: bootWatchdogPlaceholderPath })
  await page.goto('/')
  const skip = page.getByRole('button', { name: 'Skip' })
  try {
    await skip.click({ timeout: 8_000 })
  } catch {
    // Reduced-motion intro may already have dismissed itself.
  }
  await expect(page.getByText('HocusPocus UI failed to load')).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Story Lab' })).toBeVisible({ timeout: 15_000 })
  return session
}

export async function closeApp(page: Page, session: ApiRouteSession): Promise<void> {
  await page.close()
  const leftover = formatUnhandled(session)
  if (leftover) {
    throw new Error(`Unhandled API routes after boot:\n${leftover}`)
  }
}
