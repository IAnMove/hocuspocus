import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

for (const viewport of [{ width: 390, height: 667 }, { width: 667, height: 390 }]) {
  test(`image generation scrolls within the mobile viewport (${viewport.width})`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.addInitScript("localStorage.setItem('hocuspocus-wizard-sidebar-collapsed', 'true')")
    const session = await gotoApp(page)
    try {
      await page.getByRole('button', { name: 'Direct generation', exact: true }).click()
      await page.getByRole('tab', { name: 'Image', exact: true }).click()
      await page.getByRole('button', { name: /New image/ }).click()
      const panel = page.getByTestId('direct-generation-workspace')
      await expect(panel).toBeVisible()
      const scroller = panel.locator('div.overflow-y-auto').first()
      await expect.poll(() => scroller.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
      const bounds = await panel.boundingBox()
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height + 1)
      await scroller.evaluate(el => { el.scrollTop = el.scrollHeight })
      await expect.poll(() => scroller.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
      await expect.poll(() => scroller.evaluate(el => Math.abs(el.scrollHeight - el.clientHeight - el.scrollTop))).toBeLessThan(2)
    } finally {
      await closeApp(page, session)
    }
  })
}
