import { expect, test } from '@playwright/test'
import { installBootWatchdogPlaceholder } from '../helpers/bootWatchdogPlaceholder'
import { closeApp, gotoApp } from '../helpers/gotoApp'

test('seeds #root before the index.html watchdog can replace the document', async ({ page }) => {
  await page.clock.install()
  await page.route('**/assets/*.js', route => route.abort())
  await page.addInitScript(() => {
    window.localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
  })
  await page.addInitScript(installBootWatchdogPlaceholder)

  await page.goto('/')

  await expect(page.locator('#root > *')).toHaveCount(1)
  await page.clock.fastForward(10_000)
  await expect(page.getByText('HocusPocus UI failed to load')).toHaveCount(0)
  await expect(page.locator('#root')).toBeVisible()
})

test('boots Story Lab against a simulated API', async ({ page }) => {
  const session = await gotoApp(page)

  await expect(page.getByText('HocusPocus could not reach its local server.')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'HocusPocus LAN access' })).toHaveCount(0)

  const storyTab = page.getByRole('tab', { name: 'Story Lab' })
  await expect(storyTab).toBeVisible()
  await storyTab.click()

  await expect(page.getByRole('navigation', { name: 'Story Lab sections' })).toBeVisible()

  await closeApp(page, session)
})
