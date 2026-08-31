import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

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
